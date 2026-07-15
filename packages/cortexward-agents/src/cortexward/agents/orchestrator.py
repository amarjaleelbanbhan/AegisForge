"""Agent-driven `OrchestratorPort` implementation (MPS §13).

`AgentOrchestrator` runs a fixed, ordered sequence of `Agent`s over one
`RunState`, the same "run everything, return a `RunResult`" contract
`cortexward.orchestrator.sequential.SequentialOrchestrator` implements —
this is the drop-in agent-driven replacement, adding LLM-based
verification/repair/review on top of the same scan-and-correlate step.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import uuid4

from cortexward.agents.coordinator import CoordinatorAgent
from cortexward.agents.memory import InMemoryRepositoryMemory, RepositoryMemory
from cortexward.agents.memory_agent import MemoryAgent
from cortexward.agents.planner import PlannerAgent
from cortexward.agents.protocol import Agent
from cortexward.agents.repair import RepairAgent
from cortexward.agents.reviewer import ReviewerAgent
from cortexward.agents.scanner import ScannerAgent
from cortexward.agents.state import RunState
from cortexward.agents.verifier import VerifierAgent
from cortexward.ports import AnalysisRequest, CodeGraph, LLMPort, RunResult, ScannerPort


class AgentOrchestrator:
    """Implements `OrchestratorPort` by running a fixed sequence of `Agent`s over one `RunState`."""

    def __init__(self, agents: Sequence[Agent]) -> None:
        self._agents = tuple(agents)

    def run(self, request: AnalysisRequest) -> RunResult:
        state = RunState(request=request)
        for agent in self._agents:
            state = agent.run(state)
        return RunResult(
            run_id=f"run_{uuid4().hex[:16]}", findings=state.findings, patches=state.patches
        )


def default_agents(
    *,
    llm: LLMPort,
    scanners: Sequence[ScannerPort],
    repository_memory: RepositoryMemory | None = None,
    code_graphs: Mapping[str, CodeGraph] | None = None,
) -> tuple[Agent, ...]:
    """The standard Planner -> Scanner -> Verifier -> Repair -> Reviewer -> Memory -> Coordinator
    pipeline.

    `code_graphs` is passed straight through to `VerifierAgent`, mirroring
    how `scanners` is a caller-supplied dependency rather than something
    this function auto-discovers: build it with
    `cortexward.agents.code_graphs.build_code_graphs(root, languages=...)`
    once the target `root` is known (this function is request-independent,
    so it can't build that itself). Omit it to verify findings via the LLM
    alone, exactly as if reachability analysis didn't exist.
    """
    memory = repository_memory if repository_memory is not None else InMemoryRepositoryMemory()
    return (
        PlannerAgent(llm=llm),
        ScannerAgent(scanners=scanners),
        VerifierAgent(llm=llm, code_graphs=code_graphs),
        RepairAgent(llm=llm),
        ReviewerAgent(llm=llm),
        MemoryAgent(repository_memory=memory),
        CoordinatorAgent(llm=llm),
    )


__all__ = ["AgentOrchestrator", "default_agents"]
