"""LangGraph-backed `OrchestratorPort` implementation (MPS §13, ADR-0002).

ADR-0002 named LangGraph as "one adapter behind [`OrchestratorPort`]"; its own
"Consequences" section promised "freedom to swap or drop LangGraph without
touching agents or the domain." `AgentOrchestrator` (`cortexward-agents`) is
the in-process reference implementation that promise made possible without
LangGraph ever actually being wired in; `LangGraphOrchestrator` is that
promise kept — the exact same `Agent` sequence, run as a
`langgraph.graph.StateGraph` instead of a plain Python loop, with no
behavior change: same agents, same order, same `RunState` threading.

LangGraph's types never escape this module (ADR-0002's whole point):
`_GraphState` is a private `TypedDict` wrapping one `RunState` value; every
node function unwraps it, calls exactly the `Agent.run()` an
`AgentOrchestrator` would, and rewraps the result. Nothing above
`OrchestratorPort` ever sees a LangGraph type.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from cortexward.agents.protocol import Agent
from cortexward.agents.state import RunState
from cortexward.ports import AnalysisRequest, RunResult


class _GraphState(TypedDict):
    """The one value threaded through the graph.

    LangGraph's default per-key behavior (no reducer annotation) is to
    replace the previous value with whatever a node returns for that key —
    exactly what's wanted here, since `RunState` is already its own
    immutable, functionally-updated aggregate (MPS §13); no LangGraph-level
    merge semantics are needed on top of it.
    """

    run_state: RunState


class LangGraphOrchestrator:
    """Implements `OrchestratorPort` by running `Agent`s as a LangGraph `StateGraph`.

    Behaviorally identical to `AgentOrchestrator` for the same `agents`
    sequence — a linear chain, START through every agent in order to END.
    This exists to satisfy ADR-0002's own reference-adapter naming, not
    because the standard seven-agent pipeline needs graph-native features
    (conditional branching, checkpointing, cyclic retries) yet. A future
    agent that needs those — e.g. the Reviewer/Repair retry loop MPS §13
    anticipates but this v1 framework doesn't implement — is exactly what
    would justify a non-linear graph built on top of this same foundation.
    """

    def __init__(self, agents: Sequence[Agent]) -> None:
        self._agents = tuple(agents)
        graph: StateGraph[_GraphState, None, _GraphState, _GraphState] = StateGraph(_GraphState)
        previous: str = START
        for index, agent in enumerate(self._agents):
            node_name = f"{index}_{agent.name}"

            # `agent=agent` binds this iteration's agent as a default
            # argument, avoiding the classic late-binding-closure-in-loop
            # bug (every node would otherwise call whichever `agent` the
            # loop variable held *last*). Defined inline rather than
            # returned from a small factory: mypy strict fails to match a
            # `Callable[[_GraphState], _GraphState]`-typed value against
            # `StateGraph.add_node`'s generic overload set, but resolves a
            # literal nested `def` (whose type it infers structurally)
            # without issue -- a real mypy/LangGraph-stub interaction, not
            # a behavior difference.
            def _run(state: _GraphState, agent: Agent = agent) -> _GraphState:
                return {"run_state": agent.run(state["run_state"])}

            graph.add_node(node_name, _run)
            graph.add_edge(previous, node_name)
            previous = node_name
        graph.add_edge(previous, END)
        self._graph = graph.compile()

    def run(self, request: AnalysisRequest) -> RunResult:
        initial: _GraphState = {"run_state": RunState(request=request)}
        result = self._graph.invoke(initial)
        state: RunState = result["run_state"]
        return RunResult(
            run_id=f"run_{uuid4().hex[:16]}", findings=state.findings, patches=state.patches
        )


__all__ = ["LangGraphOrchestrator"]
