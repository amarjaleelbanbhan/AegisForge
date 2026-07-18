"""Unit tests for `LangGraphOrchestrator`.

Mirrors `cortexward-agents`' own `test_orchestrator.py::TestAgentOrchestrator`
suite closely on purpose: `LangGraphOrchestrator` must be behaviorally
identical to `AgentOrchestrator` for the same `agents` sequence, only the
execution engine underneath differs (ADR-0002).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import RunState
from cortexward.orchestrator import LangGraphOrchestrator
from cortexward.ports import AnalysisRequest, OrchestratorPort

pytestmark = pytest.mark.unit


class _RecordingAgent:
    """Appends its own name to a shared list every time it runs, to assert call order."""

    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self._calls = calls

    def run(self, state: RunState) -> RunState:
        self._calls.append(self.name)
        return state.with_completed(self.name)


class TestLangGraphOrchestrator:
    def test_satisfies_the_orchestrator_port_protocol(self) -> None:
        assert isinstance(LangGraphOrchestrator([]), OrchestratorPort)

    def test_runs_agents_in_order(self, tmp_path: Path) -> None:
        calls: list[str] = []
        agents = [
            _RecordingAgent("a", calls),
            _RecordingAgent("b", calls),
            _RecordingAgent("c", calls),
        ]
        orchestrator = LangGraphOrchestrator(agents)
        orchestrator.run(AnalysisRequest(root=tmp_path))
        assert calls == ["a", "b", "c"]

    def test_returns_a_run_result_with_a_generated_run_id(self, tmp_path: Path) -> None:
        orchestrator = LangGraphOrchestrator([])
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert result.run_id.startswith("run_")
        assert result.findings == ()
        assert result.patches == ()

    def test_two_runs_get_different_run_ids(self, tmp_path: Path) -> None:
        orchestrator = LangGraphOrchestrator([])
        request = AnalysisRequest(root=tmp_path)
        first = orchestrator.run(request)
        second = orchestrator.run(request)
        assert first.run_id != second.run_id

    def test_final_state_findings_and_patches_flow_into_the_result(self, tmp_path: Path) -> None:
        calls: list[str] = []
        orchestrator = LangGraphOrchestrator([_RecordingAgent("only", calls)])
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert result.findings == ()
        assert result.patches == ()
        assert calls == ["only"]

    def test_empty_agent_sequence_still_returns_a_valid_result(self, tmp_path: Path) -> None:
        orchestrator = LangGraphOrchestrator([])
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert result.run_id

    def test_two_agents_of_the_same_type_do_not_collide(self, tmp_path: Path) -> None:
        # Node names are index-prefixed precisely so a future retry loop
        # (MPS §13) could reuse the same Agent type more than once in one
        # pipeline without a LangGraph "duplicate node name" error.
        calls: list[str] = []
        agents = [_RecordingAgent("retry", calls), _RecordingAgent("retry", calls)]
        orchestrator = LangGraphOrchestrator(agents)
        orchestrator.run(AnalysisRequest(root=tmp_path))
        assert calls == ["retry", "retry"]
