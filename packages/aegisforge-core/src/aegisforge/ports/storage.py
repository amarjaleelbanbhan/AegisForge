"""Storage port: the event-sourced finding log and artifact store (ADR-0008).

Findings are persisted as an append-only sequence of events, with the current
:class:`~aegisforge.domain.Finding` state materialized from replaying them.
Reference adapters are SQLite (local) and Postgres+pgvector (server); both
implement this same protocol so the domain and application layers never
import a database driver directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from aegisforge.domain import Evidence, Finding, Patch
from aegisforge.ports._base import PortModel


class FindingEventKind(StrEnum):
    DETECTED = "detected"
    EVIDENCE_ATTACHED = "evidence_attached"
    ASSESSED = "assessed"
    PATCH_PROPOSED = "patch_proposed"
    SUPPRESSED = "suppressed"


class FindingEvent(PortModel):
    """One append-only event in a finding's history."""

    finding_id: str
    kind: FindingEventKind
    occurred_at: datetime
    evidence: Evidence | None = None
    patch: Patch | None = None
    note: str | None = None


@runtime_checkable
class StoragePort(Protocol):
    """Append-only finding events plus content-addressed artifact storage."""

    def append_event(self, event: FindingEvent) -> None:
        """Durably record ``event``. MUST NOT mutate or remove prior events."""
        ...

    def events_for(self, finding_id: str) -> Iterable[FindingEvent]:
        """Return all events for ``finding_id`` in the order they occurred."""
        ...

    def get_finding(self, finding_id: str) -> Finding | None:
        """Return the current materialized state of a finding, if known."""
        ...

    def list_findings(self, run_id: str) -> Iterable[Finding]:
        """Return the current materialized findings for a run."""
        ...

    def put_artifact(self, content: bytes) -> str:
        """Store ``content`` and return its content-addressed reference."""
        ...

    def get_artifact(self, ref: str) -> bytes:
        """Retrieve previously stored content by its reference."""
        ...
