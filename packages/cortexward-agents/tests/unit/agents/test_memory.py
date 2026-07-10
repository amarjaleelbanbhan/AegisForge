"""Unit tests for the memory abstractions (repository memory + global knowledge)."""

from __future__ import annotations

import pytest

from cortexward.agents import (
    GlobalKnowledge,
    InMemoryRepositoryMemory,
    RepositoryMemory,
    StaticGlobalKnowledge,
    fingerprint_for,
)
from cortexward.domain import Finding, Provenance, SourceLocation

pytestmark = pytest.mark.unit


def _finding(
    rule_id: str = "R1", path: str = "app.py", line: int = 1, cwe: int | None = 89
) -> Finding:
    return Finding(
        rule_id=rule_id,
        title="t",
        message="m",
        cwe=cwe,
        locations=(SourceLocation(path=path, start_line=line),),
        provenance=Provenance(producer="test"),
    )


class TestFingerprintFor:
    def test_identical_findings_produce_the_same_fingerprint(self) -> None:
        a = _finding()
        b = _finding()
        assert fingerprint_for(a) == fingerprint_for(b)

    def test_different_rule_ids_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(rule_id="A")) != fingerprint_for(_finding(rule_id="B"))

    def test_different_locations_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(line=1)) != fingerprint_for(_finding(line=2))

    def test_different_cwes_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(cwe=79)) != fingerprint_for(_finding(cwe=89))

    def test_a_finding_with_no_location_does_not_crash(self) -> None:
        finding = Finding(
            rule_id="R1", title="t", message="m", provenance=Provenance(producer="test")
        )
        assert fingerprint_for(finding)


class TestInMemoryRepositoryMemory:
    def test_satisfies_the_repository_memory_protocol(self) -> None:
        assert isinstance(InMemoryRepositoryMemory(), RepositoryMemory)

    def test_a_fresh_fingerprint_is_not_suppressed(self) -> None:
        memory = InMemoryRepositoryMemory()
        assert memory.is_suppressed("abc123") is False

    def test_recording_a_suppression_makes_it_reported(self) -> None:
        memory = InMemoryRepositoryMemory()
        memory.record_suppression("abc123", "known false positive")
        assert memory.is_suppressed("abc123") is True

    def test_suppressions_lists_every_recorded_entry(self) -> None:
        memory = InMemoryRepositoryMemory()
        memory.record_suppression("fp1", "reason one")
        memory.record_suppression("fp2", "reason two")
        records = memory.suppressions()
        assert {r.fingerprint for r in records} == {"fp1", "fp2"}

    def test_re_recording_the_same_fingerprint_overwrites_the_reason(self) -> None:
        memory = InMemoryRepositoryMemory()
        memory.record_suppression("fp1", "first reason")
        memory.record_suppression("fp1", "updated reason")
        records = memory.suppressions()
        assert len(records) == 1
        assert records[0].reason == "updated reason"


class TestStaticGlobalKnowledge:
    def test_satisfies_the_global_knowledge_protocol(self) -> None:
        assert isinstance(StaticGlobalKnowledge(), GlobalKnowledge)

    def test_known_cwe_returns_a_summary(self) -> None:
        knowledge = StaticGlobalKnowledge()
        summary = knowledge.cwe_summary(89)
        assert summary is not None
        assert "SQL Injection" in summary

    def test_unknown_cwe_returns_none(self) -> None:
        knowledge = StaticGlobalKnowledge()
        assert knowledge.cwe_summary(999999) is None
