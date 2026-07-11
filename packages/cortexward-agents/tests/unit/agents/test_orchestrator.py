"""Unit tests for `AgentOrchestrator` and `default_agents`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import (
    AgentOrchestrator,
    CoordinatorAgent,
    InMemoryRepositoryMemory,
    MemoryAgent,
    PlannerAgent,
    RepairAgent,
    ReviewerAgent,
    RunState,
    ScannerAgent,
    VerifierAgent,
    default_agents,
)
from cortexward.ports import AnalysisRequest, LLMPort

pytestmark = pytest.mark.unit


class _RecordingAgent:
    """Appends its own name to a shared list every time it runs, to assert call order."""

    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self._calls = calls

    def run(self, state: RunState) -> RunState:
        self._calls.append(self.name)
        return state.with_completed(self.name)


class _NullLLM:
    model_id = "fake-model"

    def complete(self, request: object) -> object:  # pragma: no cover - not exercised
        raise AssertionError("LLM should not be called in these tests")

    def count_tokens(self, text: str) -> int:  # pragma: no cover - not exercised
        return 0

    def cost_estimate(self, usage: object) -> float:  # pragma: no cover - not exercised
        return 0.0


class TestAgentOrchestrator:
    def test_runs_agents_in_order(self, tmp_path: Path) -> None:
        calls: list[str] = []
        agents = [
            _RecordingAgent("a", calls),
            _RecordingAgent("b", calls),
            _RecordingAgent("c", calls),
        ]
        orchestrator = AgentOrchestrator(agents)
        orchestrator.run(AnalysisRequest(root=tmp_path))
        assert calls == ["a", "b", "c"]

    def test_returns_a_run_result_with_a_generated_run_id(self, tmp_path: Path) -> None:
        orchestrator = AgentOrchestrator([])
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert result.run_id.startswith("run_")
        assert result.findings == ()
        assert result.patches == ()

    def test_two_runs_get_different_run_ids(self, tmp_path: Path) -> None:
        orchestrator = AgentOrchestrator([])
        request = AnalysisRequest(root=tmp_path)
        first = orchestrator.run(request)
        second = orchestrator.run(request)
        assert first.run_id != second.run_id

    def test_final_state_findings_and_patches_flow_into_the_result(self, tmp_path: Path) -> None:
        calls: list[str] = []
        orchestrator = AgentOrchestrator([_RecordingAgent("only", calls)])
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert result.findings == ()
        assert result.patches == ()
        assert calls == ["only"]

    def test_empty_agent_sequence_still_returns_a_valid_result(self, tmp_path: Path) -> None:
        orchestrator = AgentOrchestrator([])
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert result.run_id


class TestDefaultAgents:
    def test_returns_the_seven_agents_in_pipeline_order(self) -> None:
        llm: LLMPort = _NullLLM()  # type: ignore[assignment]
        agents = default_agents(llm=llm, scanners=())
        assert [type(agent) for agent in agents] == [
            PlannerAgent,
            ScannerAgent,
            VerifierAgent,
            RepairAgent,
            ReviewerAgent,
            MemoryAgent,
            CoordinatorAgent,
        ]

    def test_creates_its_own_repository_memory_when_none_given(self) -> None:
        llm: LLMPort = _NullLLM()  # type: ignore[assignment]
        agents = default_agents(llm=llm, scanners=())
        memory_agent = next(agent for agent in agents if isinstance(agent, MemoryAgent))
        assert isinstance(memory_agent._memory, InMemoryRepositoryMemory)

    def test_uses_the_given_repository_memory_when_provided(self) -> None:
        llm: LLMPort = _NullLLM()  # type: ignore[assignment]
        shared_memory = InMemoryRepositoryMemory()
        agents = default_agents(llm=llm, scanners=(), repository_memory=shared_memory)
        memory_agent = next(agent for agent in agents if isinstance(agent, MemoryAgent))
        assert memory_agent._memory is shared_memory
