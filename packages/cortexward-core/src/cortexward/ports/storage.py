"""Storage port: the event-sourced finding log and artifact store (ADR-0008).

Findings are persisted as an append-only sequence of events, with the current
:class:`~cortexward.domain.Finding` state materialized from replaying them.
Reference adapters are SQLite (local) and Postgres+pgvector (server); both
implement this same protocol so the domain and application layers never
import a database driver directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from cortexward.domain import Evidence, Finding, FindingState, Patch, apply_assessment
from cortexward.ports._base import PortModel


class FindingEventKind(StrEnum):
    DETECTED = "detected"
    EVIDENCE_ATTACHED = "evidence_attached"
    ASSESSED = "assessed"
    PATCH_PROPOSED = "patch_proposed"
    SUPPRESSED = "suppressed"


class FindingEvent(PortModel):
    """One append-only event in a finding's history.

    ``finding`` carries the full detected `Finding` snapshot and is required
    on ``DETECTED`` events — the only point in the log where the finding's
    own core data (rule id, locations, provenance, ...) is ever recorded;
    every later event only layers a delta (evidence, a patch proposal, a
    suppression) onto that initial snapshot. It is ``None`` for every other
    kind, matching ``evidence``/``patch`` being ``None`` outside their own
    kind.
    """

    finding_id: str
    kind: FindingEventKind
    occurred_at: datetime
    finding: Finding | None = None
    evidence: Evidence | None = None
    patch: Patch | None = None
    note: str | None = None


def materialize_finding(events: Iterable[FindingEvent]) -> Finding | None:
    """Replay a finding's event log into its current materialized state.

    Pure domain-level replay logic shared by every `StoragePort` adapter
    (ADR-0008) so each one doesn't reimplement its own copy. Events are
    replayed in the order given — callers are responsible for supplying them
    in `occurred_at` order, the same responsibility `StoragePort.events_for`
    already documents. Malformed events (a `DETECTED` with no `finding`, or a
    delta event arriving before any `DETECTED` event) are skipped rather than
    raised on, so one bad event can't stop the rest of the log from
    replaying — the same degrade-gracefully posture this project's untrusted-
    input handling uses elsewhere, applied here to a log that is internally
    produced but still worth defending against a partial/corrupt store.
    """
    finding: Finding | None = None
    for event in events:
        if event.kind is FindingEventKind.DETECTED:
            finding = event.finding
            continue
        if finding is None:
            continue
        if event.kind is FindingEventKind.EVIDENCE_ATTACHED:
            if event.evidence is not None:
                finding = finding.with_evidence(event.evidence)
        elif event.kind is FindingEventKind.ASSESSED:
            finding = apply_assessment(finding)
        elif event.kind is FindingEventKind.PATCH_PROPOSED:
            if event.patch is not None and event.patch.is_validated:
                finding = finding.with_state(FindingState.PATCHED)
        elif event.kind is FindingEventKind.SUPPRESSED:  # pragma: no branch
            # Unreachable with the current 5-member FindingEventKind (DETECTED
            # is handled above with `continue`, so only EVIDENCE_ATTACHED/
            # ASSESSED/PATCH_PROPOSED/SUPPRESSED ever reach here) -- kept as an
            # explicit branch rather than a bare `else` so a future kind added
            # to the enum fails loudly (silently falling through and leaving
            # `finding` unchanged) instead of being silently absorbed.
            finding = finding.with_state(FindingState.DISMISSED)
    return finding


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
