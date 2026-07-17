"""Unit tests for `GitHubVCSAdapter`.

High-level behavior tests monkeypatch the adapter's own `_request`/
`_request_json`, exercising the request/response mapping deterministically
against GitHub's documented REST API v3 schema (see the module docstring
for why this isn't live-verified — no credentials in this environment).
`TestRequestErrorHandling` monkeypatches `urllib.request.urlopen` directly
to exercise the real HTTP layer's error handling. `checkout()` is tested
against a real local git repository, matching this codebase's preference
for real components wherever genuinely reachable (`apply_and_rescan`'s own
tests use a real `git` binary the same way).
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from cortexward.ports import PullRequestRef, VCSPort
from cortexward.vcs import GitHubError, GitHubVCSAdapter

pytestmark = pytest.mark.unit


def _run_git(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)  # noqa: S603


def _init_local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    repo.mkdir()
    _run_git(["git", "init", "--quiet", "-b", "main"], cwd=repo)
    _run_git(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["git", "config", "user.name", "Test"], cwd=repo)
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _run_git(["git", "add", "app.py"], cwd=repo)
    _run_git(["git", "commit", "--quiet", "-m", "initial"], cwd=repo)
    return repo


class TestProtocolConformance:
    def test_satisfies_the_port(self) -> None:
        assert isinstance(GitHubVCSAdapter(token="t"), VCSPort)

    def test_host_is_github(self) -> None:
        assert GitHubVCSAdapter(token="t").host == "github"


class TestCheckout:
    def test_clones_and_checks_out_a_real_local_repository(self, tmp_path: Path) -> None:
        origin = _init_local_repo(tmp_path)
        dest = tmp_path / "work"
        adapter = GitHubVCSAdapter(token="unused-for-local-paths")

        result = adapter.checkout(str(origin), "main", dest)

        assert result == dest
        assert (dest / "app.py").read_text(encoding="utf-8") == "x = 1\n"

    def test_checks_out_a_specific_revision(self, tmp_path: Path) -> None:
        origin = _init_local_repo(tmp_path)
        _run_git(["git", "branch", "feature"], cwd=origin)
        (origin / "app.py").write_text("x = 2\n", encoding="utf-8")
        _run_git(["git", "checkout", "feature"], cwd=origin)
        _run_git(["git", "commit", "--quiet", "-am", "on feature"], cwd=origin)

        dest = tmp_path / "work"
        adapter = GitHubVCSAdapter(token="t")
        adapter.checkout(str(origin), "feature", dest)

        assert (dest / "app.py").read_text(encoding="utf-8") == "x = 2\n"

    def test_git_not_available_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        adapter = GitHubVCSAdapter(token="t")
        with pytest.raises(GitHubError, match="git is not available"):
            adapter.checkout("https://github.com/o/r", "main", tmp_path / "work")

    def test_a_nonexistent_source_raises_with_no_token_leaked(self, tmp_path: Path) -> None:
        adapter = GitHubVCSAdapter(token="super-secret-token")
        with pytest.raises(GitHubError) as exc_info:
            adapter.checkout(str(tmp_path / "does-not-exist"), "main", tmp_path / "work")
        assert "super-secret-token" not in str(exc_info.value)

    def test_a_hung_git_operation_raises_with_no_token_leaked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=300)

        monkeypatch.setattr(subprocess, "run", _timeout)
        adapter = GitHubVCSAdapter(token="super-secret-token")
        with pytest.raises(GitHubError, match="timed out") as exc_info:
            adapter.checkout("https://github.com/o/r", "main", tmp_path / "work")
        assert "super-secret-token" not in str(exc_info.value)


class TestReadDiff:
    def test_requests_the_diff_media_type_and_returns_the_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_request(
            self: GitHubVCSAdapter, path: str, *, accept: str, method: str = "GET"
        ) -> bytes:
            captured["path"] = path
            captured["accept"] = accept
            return b"--- a/x\n+++ b/x\n"

        monkeypatch.setattr(GitHubVCSAdapter, "_request", _fake_request)
        adapter = GitHubVCSAdapter(token="t")
        diff = adapter.read_diff(
            PullRequestRef(number=7, url="https://github.com/o/r/pull/7", head_sha="abc")
        )

        assert diff == "--- a/x\n+++ b/x\n"
        assert captured["path"] == "/repos/o/r/pulls/7"
        assert captured["accept"] == "application/vnd.github.v3.diff"


class TestOpenPullRequest:
    def test_sends_the_expected_payload_and_maps_the_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_request_json(
            self: GitHubVCSAdapter, path: str, *, method: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            captured["method"] = method
            captured["payload"] = payload
            return {
                "number": 42,
                "html_url": "https://github.com/o/r/pull/42",
                "head": {"sha": "deadbeef"},
            }

        monkeypatch.setattr(GitHubVCSAdapter, "_request_json", _fake_request_json)
        adapter = GitHubVCSAdapter(token="t")
        pr = adapter.open_pull_request(
            repository_url="https://github.com/o/r",
            base_branch="main",
            head_branch="fix/x",
            title="Fix SQL injection",
            body="evidence",
        )

        assert captured["path"] == "/repos/o/r/pulls"
        assert captured["method"] == "POST"
        assert captured["payload"] == {
            "title": "Fix SQL injection",
            "head": "fix/x",
            "base": "main",
            "body": "evidence",
        }
        assert pr == PullRequestRef(
            number=42, url="https://github.com/o/r/pull/42", head_sha="deadbeef"
        )

    def test_accepts_a_repository_url_with_a_git_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_request_json(
            self: GitHubVCSAdapter, path: str, *, method: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            return {"number": 1, "html_url": "https://github.com/o/r/pull/1", "head": {"sha": "x"}}

        monkeypatch.setattr(GitHubVCSAdapter, "_request_json", _fake_request_json)
        adapter = GitHubVCSAdapter(token="t")
        adapter.open_pull_request(
            repository_url="https://github.com/o/r.git",
            base_branch="main",
            head_branch="fix",
            title="t",
            body="b",
        )
        assert captured["path"] == "/repos/o/r/pulls"

    def test_an_unrecognizable_repository_url_raises(self) -> None:
        adapter = GitHubVCSAdapter(token="t")
        with pytest.raises(GitHubError, match="not a recognizable"):
            adapter.open_pull_request(
                repository_url="not-a-url",
                base_branch="main",
                head_branch="fix",
                title="t",
                body="b",
            )

    def test_an_unexpected_response_shape_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(GitHubVCSAdapter, "_request_json", lambda *a, **k: {"unexpected": True})
        adapter = GitHubVCSAdapter(token="t")
        with pytest.raises(GitHubError, match="unexpected pull request response shape"):
            adapter.open_pull_request(
                repository_url="https://github.com/o/r",
                base_branch="main",
                head_branch="fix",
                title="t",
                body="b",
            )


class TestComment:
    def test_posts_to_the_issue_comments_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_request_json(
            self: GitHubVCSAdapter, path: str, *, method: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            captured["method"] = method
            captured["payload"] = payload
            return {}

        monkeypatch.setattr(GitHubVCSAdapter, "_request_json", _fake_request_json)
        adapter = GitHubVCSAdapter(token="t")
        adapter.comment(
            PullRequestRef(number=9, url="https://github.com/o/r/pull/9", head_sha="x"),
            "looks good",
        )

        assert captured["path"] == "/repos/o/r/issues/9/comments"
        assert captured["method"] == "POST"
        assert captured["payload"] == {"body": "looks good"}

    def test_an_unrecognizable_pull_request_url_raises(self) -> None:
        adapter = GitHubVCSAdapter(token="t")
        with pytest.raises(GitHubError, match="not a recognizable"):
            adapter.comment(
                PullRequestRef(number=1, url="https://example.com/not-github", head_sha="x"), "hi"
            )


class TestRequestErrorHandling:
    def test_connection_failure_raises_github_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        adapter = GitHubVCSAdapter(token="t", base_url="http://localhost:1")
        with pytest.raises(GitHubError, match="failed"):
            adapter.comment(
                PullRequestRef(number=1, url="https://github.com/o/r/pull/1", head_sha="x"), "hi"
            )

    def test_invalid_json_response_raises_github_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeResponse:
            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"not json"

        monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse())
        adapter = GitHubVCSAdapter(token="t")
        with pytest.raises(GitHubError, match="failed"):
            adapter.comment(
                PullRequestRef(number=1, url="https://github.com/o/r/pull/1", head_sha="x"), "hi"
            )

    def test_read_diff_connection_failure_raises_github_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        adapter = GitHubVCSAdapter(token="t", base_url="http://localhost:1")
        with pytest.raises(GitHubError, match="failed"):
            adapter.read_diff(
                PullRequestRef(number=1, url="https://github.com/o/r/pull/1", head_sha="x")
            )

    def test_a_successful_request_returns_the_response_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exercises the real _request()/urlopen success path end to end
        # (every other test either monkeypatches _request itself or
        # exercises only the failure path) -- captures the real request
        # object's headers/method too, confirming the auth header is sent.
        captured: dict[str, Any] = {}

        class _FakeResponse:
            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"--- a/app.py\n+++ b/app.py\n"

        def _fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["authorization"] = request.get_header("Authorization")
            return _FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        adapter = GitHubVCSAdapter(token="real-token-value")
        diff = adapter.read_diff(
            PullRequestRef(number=5, url="https://github.com/o/r/pull/5", head_sha="x")
        )

        assert diff == "--- a/app.py\n+++ b/app.py\n"
        assert captured["url"] == "https://api.github.com/repos/o/r/pulls/5"
        assert captured["method"] == "GET"
        assert captured["authorization"] == "Bearer real-token-value"


class TestUrlParsing:
    def test_read_diff_rejects_an_unrecognizable_url(self) -> None:
        adapter = GitHubVCSAdapter(token="t")
        with pytest.raises(GitHubError, match="not a recognizable"):
            adapter.read_diff(PullRequestRef(number=1, url="not-a-url", head_sha="x"))
