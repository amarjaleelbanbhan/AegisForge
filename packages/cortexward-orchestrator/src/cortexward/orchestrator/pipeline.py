"""Builds the appropriate `OrchestratorPort` for a request (MPS §13/§20).

Every delivery surface (`ward scan`, the REST API, ...) needs to make the
same decision — plain scan-and-correlate when no LLM is configured,
agent-driven verification when one is — so it's written and tested once
here rather than duplicated per surface. This is the one place
`cortexward-orchestrator` depends on `cortexward-agents`: coordinating
*which* `OrchestratorPort` implementation a request gets is itself part of
this package's job (its own module docstring already says the orchestrator
"sits above the peer-adapter layer, not beside it").
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from cortexward.agents import AgentOrchestrator, build_code_graphs, default_agents
from cortexward.llm import LLMProviderConfig, build_llm
from cortexward.orchestrator.langgraph_orchestrator import LangGraphOrchestrator
from cortexward.orchestrator.sequential import SequentialOrchestrator, default_scanners
from cortexward.ports import OrchestratorPort
from cortexward.sandbox import DockerSandboxAdapter
from cortexward.storage import SqliteStoragePort

#: The execution engine for the LLM-driven agent pipeline. `"agent"` runs the
#: plain Python `AgentOrchestrator` loop; `"langgraph"` runs the exact same
#: agent sequence as a `langgraph.graph.StateGraph` instead (ADR-0002).
#: Meaningless when `llm_config` is `None` (no agents to run either way).
Engine = Literal["agent", "langgraph"]


def build_pipeline(
    *,
    llm_config: LLMProviderConfig | None,
    root: Path,
    languages: Sequence[str] = (),
    reachability: bool = True,
    engine: Engine = "agent",
    sandbox: bool = False,
) -> OrchestratorPort:
    """`SequentialOrchestrator` when `llm_config` is `None`, an agent-driven
    orchestrator otherwise — `AgentOrchestrator` or `LangGraphOrchestrator`
    per `engine`, both running the identical `default_agents()` sequence.

    `root`/`languages` are only used to build a `CodeGraph` for reachability
    evidence (`reachability=False` skips that step); every configured
    scanner (`default_scanners()`) still runs either way.

    `sandbox=True` adds dynamic exploit verification (`PocAgent`, Verification
    Ladder rung 3): a `DockerSandboxAdapter` plus a shared in-memory
    `SqliteStoragePort` (the artifact store `PocAgent` stages the bundle into
    and the sandbox reads it back from — one instance so both see the same
    artifacts) are handed to `default_agents`, which inserts `PocAgent`
    between Verifier and Repair. Constructing the adapter needs no running
    Docker daemon — a missing/unreachable daemon only surfaces when a PoC
    actually executes, where `PocAgent` treats it as inconclusive (no
    evidence), never a crash or a false "safe". Ignored without an
    `llm_config`, matching how `reachability`/`engine` are.
    """
    scanners = default_scanners()
    if llm_config is None:
        return SequentialOrchestrator(scanners=scanners)
    llm = build_llm(llm_config)
    code_graphs = build_code_graphs(root, languages=languages) if reachability else None
    # One shared store: PocAgent stages the PoC bundle into it, the sandbox
    # reads it back by the same reference. None when --sandbox is off, so
    # default_agents omits PocAgent (it needs all three of sandbox/artifacts/root).
    store = SqliteStoragePort() if sandbox else None
    agents = default_agents(
        llm=llm,
        scanners=scanners,
        code_graphs=code_graphs,
        sandbox=DockerSandboxAdapter(store) if store is not None else None,
        artifacts=store,
        root=root,
    )
    if engine == "langgraph":
        return LangGraphOrchestrator(agents)
    return AgentOrchestrator(agents)


__all__ = ["Engine", "build_pipeline"]
