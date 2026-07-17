"""Conformance test for the Storage port."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from cortexward.domain import Finding
from cortexward.ports import FindingEvent, FindingEventKind, StoragePort

pytestmark = pytest.mark.unit


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
