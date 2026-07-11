"""Unit tests for `MemoryAgent`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import InMemoryRepositoryMemory, MemoryAgent, RunState, fingerprint_for
from cortexward.domain import Finding, FindingState, Provenance, SourceLocation
from cortexward.ports import AnalysisRequest

pytestmark = pytest.mark.unit


def _finding(rule_id: str = "R1", state: FindingState = FindingState.CANDIDATE) -> Finding:
    finding = Finding(
        rule_id=rule_id,
        title="t",
        message="m",
        locations=(SourceLocation(path="app.py", start_line=1),),
        provenance=Provenance(producer="test"),
    )
    return finding.with_state(state)


class TestMemoryAgent:
    def test_name_is_memory(self) -> None:
        assert MemoryAgent(repository_memory=InMemoryRepositoryMemory()).name == "memory"

    def test_findings_matching_a_known_suppression_are_dismissed(self, tmp_path: Path) -> None:
        memory = InMemoryRepositoryMemory()
        finding = _finding()
        memory.record_suppression(fingerprint_for(finding), reason="known false positive")
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        result = agent.run(state)
        assert result.findings[0].state == FindingState.DISMISSED

    def test_findings_not_suppressed_are_left_alone(self, tmp_path: Path) -> None:
        memory = InMemoryRepositoryMemory()
        finding = _finding()
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        result = agent.run(state)
        assert result.findings[0].state == FindingState.CANDIDATE

    def test_refuted_findings_are_persisted_as_new_suppressions(self, tmp_path: Path) -> None:
        memory = InMemoryRepositoryMemory()
        finding = _finding(state=FindingState.REFUTED)
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        agent.run(state)
        assert memory.is_suppressed(fingerprint_for(finding)) is True

    def test_already_suppressed_refuted_finding_is_not_persisted_twice(
        self, tmp_path: Path
    ) -> None:
        memory = InMemoryRepositoryMemory()
        finding = _finding(state=FindingState.REFUTED)
        memory.record_suppression(fingerprint_for(finding), reason="first pass")
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        agent.run(state)
        assert len(memory.suppressions()) == 1
        assert memory.suppressions()[0].reason == "first pass"

    def test_verified_findings_are_neither_dismissed_nor_persisted(self, tmp_path: Path) -> None:
        memory = InMemoryRepositoryMemory()
        finding = _finding(state=FindingState.VERIFIED)
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        result = agent.run(state)
        assert result.findings[0].state == FindingState.VERIFIED
        assert memory.suppressions() == ()

    def test_note_reports_dismissed_and_persisted_counts(self, tmp_path: Path) -> None:
        memory = InMemoryRepositoryMemory()
        suppressed = _finding("S")
        memory.record_suppression(fingerprint_for(suppressed), reason="known")
        refuted = _finding("R", state=FindingState.REFUTED)
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (suppressed, refuted)
        )
        result = agent.run(state)
        assert result.notes_from("memory") == (
            "1 dismissed from memory; 1 new suppression(s) recorded",
        )

    def test_marks_itself_completed(self, tmp_path: Path) -> None:
        agent = MemoryAgent(repository_memory=InMemoryRepositoryMemory())
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("memory",)

    def test_findings_replace_not_append(self, tmp_path: Path) -> None:
        memory = InMemoryRepositoryMemory()
        finding_a, finding_b = _finding("A"), _finding("B")
        agent = MemoryAgent(repository_memory=memory)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (finding_a, finding_b)
        )
        result = agent.run(state)
        assert len(result.findings) == 2
