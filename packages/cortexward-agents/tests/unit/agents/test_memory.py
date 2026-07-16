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
from cortexward.domain import fingerprint_for as domain_fingerprint_for

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


class TestFingerprintForReExport:
    """The full behavioral suite now lives in cortexward-core's
    test_fingerprint.py, since `fingerprint_for` moved to `cortexward.domain`
    (a domain-level identity concept, not agent-specific) — this just
    confirms the re-export `cortexward.agents` still exposes is wired to the
    real implementation, not a stale copy."""

    def test_re_exported_fingerprint_for_matches_the_domain_implementation(self) -> None:
        finding = _finding()
        assert fingerprint_for(finding) == domain_fingerprint_for(finding)


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
