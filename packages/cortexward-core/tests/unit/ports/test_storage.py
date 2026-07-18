"""Conformance test for the Storage port."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

import pytest

from cortexward.domain import Evidence, EvidenceKind, Finding, FindingState, Patch, Provenance
from cortexward.ports import FindingEvent, FindingEventKind, StoragePort, materialize_finding

pytestmark = pytest.mark.unit

MakeFinding = Callable[..., Finding]
MakeEvidence = Callable[..., Evidence]

_PROV = Provenance(producer="test", producer_version="0")


def _detected(finding: Finding, *, when: datetime | None = None) -> FindingEvent:
    return FindingEvent(
        finding_id=finding.id,
        kind=FindingEventKind.DETECTED,
        occurred_at=when or datetime.now(UTC),
        finding=finding,
    )


def _make_patch(
    finding_id: str,
    *,
    tests_pass: bool | None = None,
    rescan_clean: bool | None = None,
    exploit_neutralized: bool | None = None,
) -> Patch:
    return Patch(
        finding_id=finding_id,
        diff="--- a\n+++ b\n",
        description="fix it",
        provenance=_PROV,
        tests_pass=tests_pass,
        rescan_clean=rescan_clean,
        exploit_neutralized=exploit_neutralized,
    )


class _InMemoryStorage:
    """An append-only event log with a trivial materialized-state cache."""

    def __init__(self) -> None:
        self._events: dict[str, list[FindingEvent]] = {}
        self._materialized: dict[str, Finding] = {}
        self._artifacts: dict[str, bytes] = {}

    def append_event(self, event: FindingEvent) -> None:
        self._events.setdefault(event.finding_id, []).append(event)

    def events_for(self, finding_id: str) -> Iterable[FindingEvent]:
        return tuple(self._events.get(finding_id, ()))

    def register_materialized(self, finding: Finding) -> None:
        self._materialized[finding.id] = finding

    def get_finding(self, finding_id: str) -> Finding | None:
        return self._materialized.get(finding_id)

    def list_findings(self, run_id: str) -> Iterable[Finding]:
        return tuple(self._materialized.values())

    def put_artifact(self, content: bytes) -> str:
        ref = f"sha256:{hash(content):x}"
        self._artifacts[ref] = content
        return ref

    def get_artifact(self, ref: str) -> bytes:
        return self._artifacts[ref]


def test_fake_storage_satisfies_protocol() -> None:
    assert isinstance(_InMemoryStorage(), StoragePort)


def test_events_are_appended_in_order() -> None:
    storage = _InMemoryStorage()
    storage.append_event(
        FindingEvent(
            finding_id="find_1", kind=FindingEventKind.DETECTED, occurred_at=datetime.now(UTC)
        )
    )
    storage.append_event(
        FindingEvent(
            finding_id="find_1", kind=FindingEventKind.ASSESSED, occurred_at=datetime.now(UTC)
        )
    )
    kinds = [e.kind for e in storage.events_for("find_1")]
    assert kinds == [FindingEventKind.DETECTED, FindingEventKind.ASSESSED]


def test_artifact_round_trip() -> None:
    storage = _InMemoryStorage()
    ref = storage.put_artifact(b"poc-script")
    assert storage.get_artifact(ref) == b"poc-script"


def test_unknown_finding_returns_none() -> None:
    assert _InMemoryStorage().get_finding("nope") is None


class TestMaterializeFinding:
    """`materialize_finding` replays a finding's event log (ADR-0008)."""

    def test_empty_log_materializes_to_none(self) -> None:
        assert materialize_finding([]) is None

    def test_detected_event_materializes_the_snapshot(self, make_finding: MakeFinding) -> None:
        finding = make_finding()
        assert materialize_finding([_detected(finding)]) == finding

    def test_a_delta_event_before_any_detected_event_is_ignored(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding()
        orphan_evidence_event = FindingEvent(
            finding_id=finding.id,
            kind=FindingEventKind.EVIDENCE_ATTACHED,
            occurred_at=datetime.now(UTC),
            evidence=make_evidence(),
        )
        assert materialize_finding([orphan_evidence_event]) is None

    def test_evidence_attached_accumulates_onto_the_detected_snapshot(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding()
        new_evidence = make_evidence(EvidenceKind.TAINT_TRACE)
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.EVIDENCE_ATTACHED,
                occurred_at=datetime.now(UTC),
                evidence=new_evidence,
            ),
        ]
        result = materialize_finding(events)
        assert result is not None
        assert new_evidence in result.evidence

    def test_an_evidence_attached_event_with_no_evidence_leaves_the_finding_unchanged(
        self, make_finding: MakeFinding
    ) -> None:
        finding = make_finding()
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.EVIDENCE_ATTACHED,
                occurred_at=datetime.now(UTC),
            ),
        ]
        assert materialize_finding(events) == finding

    def test_assessed_recomputes_state_from_accumulated_evidence(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.STATIC_MATCH),
            make_evidence(EvidenceKind.TAINT_TRACE),
        )
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.ASSESSED,
                occurred_at=datetime.now(UTC),
            ),
        ]
        result = materialize_finding(events)
        assert result is not None
        assert result.state is not FindingState.CANDIDATE

    def test_a_fully_validated_patch_proposal_marks_the_finding_patched(
        self, make_finding: MakeFinding
    ) -> None:
        finding = make_finding()
        patch = _make_patch(
            finding.id, tests_pass=True, rescan_clean=True, exploit_neutralized=True
        )
        assert patch.is_validated is True
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.PATCH_PROPOSED,
                occurred_at=datetime.now(UTC),
                patch=patch,
            ),
        ]
        result = materialize_finding(events)
        assert result is not None
        assert result.state is FindingState.PATCHED

    def test_an_unvalidated_patch_proposal_does_not_change_state(
        self, make_finding: MakeFinding
    ) -> None:
        finding = make_finding()
        patch = _make_patch(finding.id, tests_pass=True)
        assert patch.is_validated is False
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.PATCH_PROPOSED,
                occurred_at=datetime.now(UTC),
                patch=patch,
            ),
        ]
        result = materialize_finding(events)
        assert result is not None
        assert result.state is finding.state

    def test_suppressed_marks_the_finding_dismissed(self, make_finding: MakeFinding) -> None:
        finding = make_finding()
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.SUPPRESSED,
                occurred_at=datetime.now(UTC),
                note="accepted risk",
            ),
        ]
        result = materialize_finding(events)
        assert result is not None
        assert result.state is FindingState.DISMISSED

    def test_events_replay_in_the_order_given_not_sorted(self, make_finding: MakeFinding) -> None:
        finding = make_finding()
        patch = _make_patch(
            finding.id, tests_pass=True, rescan_clean=True, exploit_neutralized=True
        )
        events = [
            _detected(finding),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.PATCH_PROPOSED,
                occurred_at=datetime.now(UTC),
                patch=patch,
            ),
            FindingEvent(
                finding_id=finding.id,
                kind=FindingEventKind.SUPPRESSED,
                occurred_at=datetime.now(UTC),
            ),
        ]
        result = materialize_finding(events)
        assert result is not None
        # Suppressed was replayed last, so it wins over the earlier patch state
        # -- the function trusts caller-supplied order, it does not re-sort.
        assert result.state is FindingState.DISMISSED
