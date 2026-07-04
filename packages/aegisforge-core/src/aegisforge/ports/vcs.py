"""VCS port: a host-agnostic view over GitHub/GitLab/Bitbucket/Azure DevOps
and local repositories (MPS §21).

Host-specific auth and API calls live entirely in adapters; the engine only
ever depends on this protocol, so AegisForge orchestration logic is identical
whether the target repo lives on GitHub or on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from aegisforge.ports._base import PortModel


class PullRequestRef(PortModel):
    """A reference to an opened pull/merge request."""

    number: int
    url: str
    head_sha: str


@runtime_checkable
class VCSPort(Protocol):
    """A version-control host or local repository adapter."""

    @property
    def host(self) -> str:
        """Identifies the host, e.g. ``"github"``, ``"local"``."""
        ...

    def checkout(self, repository_url: str, revision: str, dest: Path) -> Path:
        """Clone/checkout ``repository_url`` at ``revision`` into ``dest``."""
        ...

    def read_diff(self, pull_request: PullRequestRef) -> str:
        """Return the unified diff for ``pull_request``."""
        ...

    def open_pull_request(
        self,
        *,
        repository_url: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
    ) -> PullRequestRef:
        """Open a pull/merge request. Never called for auto-merge — patches
        are always proposed for human review (MPS §16)."""
        ...

    def comment(self, pull_request: PullRequestRef, body: str) -> None:
        """Post a review comment on ``pull_request``."""
        ...
