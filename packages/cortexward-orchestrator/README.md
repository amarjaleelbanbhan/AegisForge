# cortexward-orchestrator

`OrchestratorPort` implementations for
[CortexWard](https://github.com/amarjaleelbanbhan/CortexWard) (MPS §13, ADR-0002).

Ships `SequentialOrchestrator`: runs every configured scanner, then normalizes and correlates
their results into `Finding`s via `cortexward.scanners.correlate`. No LLM or agent reasoning yet
— the reference in-process orchestrator that "run every scanner and merge the results" needs
before any agent-driven planning/verification/repair (later Phase 4 work) enters the picture.

Also ships `LangGraphOrchestrator`: the LangGraph-backed `OrchestratorPort` implementation
ADR-0002 named as "one adapter behind" the port. Runs the exact same `Agent` sequence
`AgentOrchestrator` (`cortexward-agents`) does — a linear chain, `START` through every agent in
order to `END` — as a `langgraph.graph.StateGraph` instead of a plain Python loop, with no
behavior change. LangGraph's own types never escape the module: a private `TypedDict` wraps the
one `RunState` value threaded through the graph.

```python
from cortexward.orchestrator import LangGraphOrchestrator
from cortexward.agents import default_agents

orchestrator = LangGraphOrchestrator(default_agents(llm=my_llm, scanners=my_scanners))
result = orchestrator.run(request)  # identical RunResult shape to AgentOrchestrator
```

Not wired into `build_pipeline()`/`ward scan` — `build_pipeline()` still picks between
`SequentialOrchestrator` and `AgentOrchestrator` (identical behavior, no LangGraph engine
involved), since exposing a third execution-engine choice through the CLI is a delivery-surface
decision (a new flag, a new default) this package doesn't make unilaterally. `LangGraphOrchestrator`
is available today for any caller that constructs an `OrchestratorPort` directly.
