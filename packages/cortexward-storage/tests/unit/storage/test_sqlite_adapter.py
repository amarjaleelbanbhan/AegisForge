"""Real-database tests for `SqliteStoragePort` -- no mocking, real sqlite3."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from cortexward.domain import Evidence, EvidenceKind, Finding, FindingState, Provenance, Severity
from cortexward.domain import SourceLocation as Loc
from cortexward.ports import FindingEvent, FindingEventKind, StoragePort
from cortexward.storage import SqliteStoragePort

pytestmark = pytest.mark.unit

_PROV = Provenance(producer="test", producer_version="0")


def _finding(*, run_id: str | None = "run_1", finding_id: str = "") -> Finding:
    return Finding(
        id=finding_id or f"find_{uuid4().hex[:16]}",
        rule_id="test.rule",
        title="Test finding",
        message="A potential issue was detected.",
        severity=Severity.HIGH,
        cwe=89,
        locations=(Loc(path="app/main.py", start_line=10),),
        provenance=Provenance(producer="test", run_id=run_id),
    )


def _evidence() -> Evidence:
    return Evidence(
        kind=EvidenceKind.TAINT_TRACE,
        summary="traced",
        provenance=_PROV,
    )


def _detected(finding: Finding) -> FindingEvent:
    return FindingEvent(
        finding_id=finding.id,
        kind=FindingEventKind.DETECTED,
        occurred_at=datetime.now(UTC),
        finding=finding,
    )


class TestProtocolConformance:
    def test_satisfies_the_storage_port_protocol(self) -> None:
        with SqliteStoragePort() as storage:
            assert isinstance(storage, StoragePort)


class TestEventLog:
    def test_events_for_an_unknown_finding_is_empty(self) -> None:
        with SqliteStoragePort() as storage:
            assert tuple(storage.events_for("nope")) == ()

    def test_appended_events_round_trip_intact(self) -> None:
        finding = _finding()
        with SqliteStoragePort() as storage:
            storage.append_event(_detected(finding))
            events = tuple(storage.events_for(finding.id))
        assert len(events) == 1
        assert events[0].kind is FindingEventKind.DETECTED
        assert events[0].finding == finding

    def test_events_are_returned_in_append_order(self) -> None:
        finding = _finding()
        with SqliteStoragePort() as storage:
            storage.append_event(_detected(finding))
            storage.append_event(
                FindingEvent(
                    finding_id=finding.id,
                    kind=FindingEventKind.EVIDENCE_ATTACHED,
                    occurred_at=datetime.now(UTC),
                    evidence=_evidence(),
                )
            )
            storage.append_event(
                FindingEvent(
                    finding_id=finding.id,
                    kind=FindingEventKind.SUPPRESSED,
                    occurred_at=datetime.now(UTC),
                )
            )
            kinds = [e.kind for e in storage.events_for(finding.id)]
        assert kinds == [
            FindingEventKind.DETECTED,
            FindingEventKind.EVIDENCE_ATTACHED,
            FindingEventKind.SUPPRESSED,
        ]


class TestGetFinding:
    def test_unknown_finding_returns_none(self) -> None:
        with SqliteStoragePort() as storage:
            assert storage.get_finding("nope") is None

    def test_materializes_from_the_replayed_event_log(self) -> None:
        finding = _finding()
        with SqliteStoragePort() as storage:
            storage.append_event(_detected(finding))
            storage.append_event(
                FindingEvent(
                    finding_id=finding.id,
                    kind=FindingEventKind.SUPPRESSED,
                    occurred_at=datetime.now(UTC),
                )
            )
            result = storage.get_finding(finding.id)
        assert result is not None
        assert result.state is FindingState.DISMISSED


class TestListFindings:
    def test_no_events_at_all_lists_nothing(self) -> None:
        with SqliteStoragePort() as storage:
            assert tuple(storage.list_findings("run_1")) == ()

    def test_lists_only_findings_whose_provenance_matches_the_run(self) -> None:
        in_run = _finding(run_id="run_1", finding_id="find_in_run")
        other_run = _finding(run_id="run_2", finding_id="find_other_run")
        with SqliteStoragePort() as storage:
            storage.append_event(_detected(in_run))
            storage.append_event(_detected(other_run))
            results = tuple(storage.list_findings("run_1"))
        assert [f.id for f in results] == ["find_in_run"]

    def test_a_finding_with_no_run_id_never_matches(self) -> None:
        no_run = _finding(run_id=None, finding_id="find_no_run")
        with SqliteStoragePort() as storage:
            storage.append_event(_detected(no_run))
            assert tuple(storage.list_findings("run_1")) == ()


class TestArtifacts:
    def test_round_trips_stored_content(self) -> None:
        with SqliteStoragePort() as storage:
            ref = storage.put_artifact(b"poc-script")
            assert storage.get_artifact(ref) == b"poc-script"

    def test_ref_is_content_addressed(self) -> None:
        with SqliteStoragePort() as storage:
            ref_a = storage.put_artifact(b"same content")
            ref_b = storage.put_artifact(b"same content")
            assert ref_a == ref_b

    def test_unknown_ref_raises_key_error(self) -> None:
        with SqliteStoragePort() as storage, pytest.raises(KeyError):
            storage.get_artifact("sha256:doesnotexist")


class TestPersistence:
    def test_defaults_to_an_in_memory_database(self) -> None:
        finding = _finding()
        with SqliteStoragePort() as first, SqliteStoragePort() as second:
            first.append_event(_detected(finding))
            assert second.get_finding(finding.id) is None

    def test_persists_across_connections_to_the_same_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "storage.sqlite3"
        finding = _finding()
        with SqliteStoragePort(db_path) as writer:
            writer.append_event(_detected(finding))

        with SqliteStoragePort(db_path) as reader:
            assert reader.get_finding(finding.id) == finding

    def test_accepts_a_string_path_as_well_as_a_path_object(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "storage.sqlite3")
        finding = _finding()
        with SqliteStoragePort(db_path) as writer:
            writer.append_event(_detected(finding))

        with SqliteStoragePort(db_path) as reader:
            assert reader.get_finding(finding.id) == finding
