"""Conformance test for the VCS port."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.ports import PullRequestRef, VCSPort

pytestmark = pytest.mark.unit


class _FakeVCS:
    host = "fake-github"

    def __init__(self) -> None:
        self.comments: list[tuple[int, str]] = []
        self._next_pr = 1

    def checkout(self, repository_url: str, revision: str, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    def read_diff(self, pull_request: PullRequestRef) -> str:
        return "--- a\n+++ b\n"

    def open_pull_request(
        self,
        *,
        repository_url: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
    ) -> PullRequestRef:
        ref = PullRequestRef(
            number=self._next_pr, url=f"{repository_url}/pull/{self._next_pr}", head_sha="deadbeef"
        )
        self._next_pr += 1
        return ref

    def comment(self, pull_request: PullRequestRef, body: str) -> None:
        self.comments.append((pull_request.number, body))


def test_fake_vcs_satisfies_protocol() -> None:
    assert isinstance(_FakeVCS(), VCSPort)


def test_checkout_and_pull_request_flow(tmp_path: Path) -> None:
    vcs = _FakeVCS()
    dest = vcs.checkout("https://example/repo", "main", tmp_path / "work")
    assert dest.exists()

    pr = vcs.open_pull_request(
        repository_url="https://example/repo",
        base_branch="main",
        head_branch="fix/x",
        title="Fix SQL injection",
        body="evidence attached",
    )
    assert pr.number == 1
    vcs.comment(pr, "looks good")
    assert vcs.comments == [(1, "looks good")]
