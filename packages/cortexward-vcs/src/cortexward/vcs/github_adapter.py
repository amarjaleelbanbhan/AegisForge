"""A `VCSPort` adapter for GitHub's REST API (MPS §17.1, §21).

Calls GitHub's REST API v3 directly via `urllib.request` (no `PyGithub`
dependency), matching every other host-calling adapter in this codebase
(`OsvScanner`, every `LLMPort` adapter): a fixed timeout, no shell, JSON
request/response only. `checkout()` is the one operation that shells out
to a real subprocess (`git`) instead, since GitHub's API has no "clone a
repo" endpoint — matching `apply_and_rescan`'s own `git` invocation style
(resolved via `shutil.which`, never a bare `"git"` argv entry, a bounded
timeout).

**Not live-verified.** This environment has no GitHub token with write
access to a real repository. The request/response mapping is written
against GitHub's published REST API v3 schema and unit-tested against
that documented shape (deterministic, no network) — the same caveat
`AnthropicAdapter`/`GeminiAdapter` carry, and for the same reason: treat
this as a reference implementation to validate against a real account
before depending on it in production.

A GitHub *App* (JWT + installation-token exchange, a webhook receiver)
is a separate, larger integration this adapter deliberately doesn't
attempt. This adapter accepts a single bearer token — a personal access
token or an already-exchanged installation token — and doesn't care
which. Registering an actual GitHub App is an owner-account action
(naming, requested permission scopes, public/private, webhook secret
provisioning) this project can't make unilaterally.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cortexward.ports import PullRequestRef

_REQUEST_TIMEOUT_SECONDS = 30
_GIT_TIMEOUT_SECONDS = 300
_API_VERSION = "2022-11-28"

_PR_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?$"
)
_REPO_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


class GitHubError(RuntimeError):
    """Raised when the GitHub API/CLI can't be reached or returns an unusable result."""


def _parse_repository_url(repository_url: str) -> tuple[str, str]:
    match = _REPO_URL_PATTERN.match(repository_url)
    if match is None:
        raise GitHubError(f"not a recognizable GitHub repository URL: {repository_url!r}")
    return match.group("owner"), match.group("repo")


def _parse_pull_request_url(url: str) -> tuple[str, str, int]:
    match = _PR_URL_PATTERN.match(url)
    if match is None:
        raise GitHubError(f"not a recognizable GitHub pull request URL: {url!r}")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def _pull_request_ref_from(response: dict[str, Any]) -> PullRequestRef:
    number = response.get("number")
    html_url = response.get("html_url")
    head = response.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if (
        not isinstance(number, int)
        or not isinstance(html_url, str)
        or not isinstance(head_sha, str)
    ):
        raise GitHubError(f"unexpected pull request response shape: {response!r}")
    return PullRequestRef(number=number, url=html_url, head_sha=head_sha)


class GitHubVCSAdapter:
    """`VCSPort` adapter for github.com and GitHub Enterprise Server."""

    host = "github"

    def __init__(self, *, token: str, base_url: str = "https://api.github.com") -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")

    def checkout(self, repository_url: str, revision: str, dest: Path) -> Path:
        git = shutil.which("git")
        if git is None:
            raise GitHubError("git is not available on PATH")
        dest.mkdir(parents=True, exist_ok=True)
        authenticated_url = self._with_token(repository_url)
        self._run_git(
            [git, "clone", "--quiet", authenticated_url, str(dest)],
            cwd=dest.parent,
            source_for_errors=repository_url,
        )
        self._run_git(
            [git, "-C", str(dest), "checkout", "--quiet", revision],
            cwd=dest.parent,
            source_for_errors=repository_url,
        )
        return dest

    def read_diff(self, pull_request: PullRequestRef) -> str:
        owner, repo, number = _parse_pull_request_url(pull_request.url)
        raw = self._request(
            f"/repos/{owner}/{repo}/pulls/{number}", accept="application/vnd.github.v3.diff"
        )
        return raw.decode("utf-8")

    def open_pull_request(
        self,
        *,
        repository_url: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
    ) -> PullRequestRef:
        owner, repo = _parse_repository_url(repository_url)
        response = self._request_json(
            f"/repos/{owner}/{repo}/pulls",
            method="POST",
            payload={"title": title, "head": head_branch, "base": base_branch, "body": body},
        )
        return _pull_request_ref_from(response)

    def comment(self, pull_request: PullRequestRef, body: str) -> None:
        owner, repo, number = _parse_pull_request_url(pull_request.url)
        self._request_json(
            f"/repos/{owner}/{repo}/issues/{number}/comments", method="POST", payload={"body": body}
        )

    def _with_token(self, repository_url: str) -> str:
        # GitHub accepts any non-empty username with a token as the
        # password over HTTPS git operations; "x-access-token" is GitHub's
        # own documented convention and works for both a personal access
        # token and a GitHub App installation token.
        if not repository_url.startswith("https://"):
            return repository_url
        return repository_url.replace("https://", f"https://x-access-token:{self._token}@", 1)

    def _run_git(self, argv: list[str], *, cwd: Path, source_for_errors: str) -> None:
        try:
            process = subprocess.run(  # noqa: S603 # nosec B603
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitHubError(f"git operation on {source_for_errors} timed out") from exc
        if process.returncode != 0:
            # git can echo the URL it tried back in its own error message
            # (e.g. "repository ... not found"), which would otherwise leak
            # the embedded access token into logs/exceptions.
            sanitized_stderr = (process.stderr or "").replace(self._token, "***REDACTED***")
            raise GitHubError(
                f"git operation on {source_for_errors} failed (exit {process.returncode}): "
                f"{sanitized_stderr.strip()}"
            )

    def _request(self, path: str, *, accept: str, method: str = "GET") -> bytes:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "X-GitHub-Api-Version": _API_VERSION,
        }
        request = urllib.request.Request(url, headers=headers, method=method)  # noqa: S310 # nosec B310
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
                return bytes(response.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubError(f"request to {path} failed: {exc}") from exc

    def _request_json(
        self, path: str, *, method: str, payload: dict[str, object]
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": _API_VERSION,
        }
        request = urllib.request.Request(  # noqa: S310 # nosec B310
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
                return dict(json.loads(response.read()))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise GitHubError(f"request to {path} failed: {exc}") from exc


__all__ = ["GitHubError", "GitHubVCSAdapter"]
