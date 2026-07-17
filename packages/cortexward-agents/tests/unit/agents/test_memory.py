"""Unit tests for the memory abstractions (repository memory + global knowledge)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import (
    GlobalKnowledge,
    InMemoryRepositoryMemory,
    RepositoryMemory,
    SqliteRepositoryMemory,
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


class TestSqliteRepositoryMemory:
    def test_satisfies_the_repository_memory_protocol(self) -> None:
        with SqliteRepositoryMemory() as memory:
            assert isinstance(memory, RepositoryMemory)

    def test_a_fresh_fingerprint_is_not_suppressed(self) -> None:
        with SqliteRepositoryMemory() as memory:
            assert memory.is_suppressed("abc123") is False

    def test_recording_a_suppression_makes_it_reported(self) -> None:
        with SqliteRepositoryMemory() as memory:
            memory.record_suppression("abc123", "known false positive")
            assert memory.is_suppressed("abc123") is True

    def test_suppressions_lists_every_recorded_entry(self) -> None:
        with SqliteRepositoryMemory() as memory:
            memory.record_suppression("fp1", "reason one")
            memory.record_suppression("fp2", "reason two")
            records = memory.suppressions()
            assert {r.fingerprint for r in records} == {"fp1", "fp2"}

    def test_re_recording_the_same_fingerprint_overwrites_the_reason(self) -> None:
        with SqliteRepositoryMemory() as memory:
            memory.record_suppression("fp1", "first reason")
            memory.record_suppression("fp1", "updated reason")
            records = memory.suppressions()
            assert len(records) == 1
            assert records[0].reason == "updated reason"

    def test_defaults_to_an_in_memory_database(self) -> None:
        # Two separate :memory: instances must not share state -- each is
        # its own private, ephemeral SQLite database.
        with SqliteRepositoryMemory() as first, SqliteRepositoryMemory() as second:
            first.record_suppression("fp1", "reason")
            assert second.is_suppressed("fp1") is False

    def test_persists_across_connections_to_the_same_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.sqlite3"
        with SqliteRepositoryMemory(db_path) as writer:
            writer.record_suppression("fp1", "known false positive")
            written = writer.suppressions()

        with SqliteRepositoryMemory(db_path) as reader:
            assert reader.is_suppressed("fp1") is True
            assert reader.suppressions() == written

    def test_accepts_a_string_path_as_well_as_a_path_object(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "memory.sqlite3")
        with SqliteRepositoryMemory(db_path) as writer:
            writer.record_suppression("fp1", "reason")

        with SqliteRepositoryMemory(db_path) as reader:
            assert reader.is_suppressed("fp1") is True


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
