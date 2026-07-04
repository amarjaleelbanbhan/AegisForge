# ADR-0002: In-process orchestration behind a port

**Status:** Accepted · **Date:** 2026-07-05 · **Amends:** the original Phase-0 "LangGraph" decision

## Context
The research brief proposed microservices + a message queue. For a tool people install and run in
CI, that is premature operational complexity. Separately, committing the application interface to
LangGraph's types would create lock-in for a young, fast-moving library over a 3–5 year core.

## Decision
Orchestrate agents **in-process** as a typed, inspectable state machine, defined by an
`OrchestratorPort`. **LangGraph is one adapter behind that port**; its types never appear in the
domain or application interfaces. Distribution/scale-out is added later via a `QueuePort` adapter,
not a rewrite.

## Consequences
- Trivial self-hosting and CI usage; no broker to operate.
- Freedom to swap or drop LangGraph without touching agents or the domain.
- A thin abstraction layer to maintain over the orchestration library.

## Alternatives considered
- **Microservices + queue now.** Rejected: ops overhead unjustified pre-scale.
- **Direct LangGraph coupling.** Rejected: lock-in to an immature dependency.

*Specified in [MPS §13](../specifications/MPS-v1.0.md#13-agent-architecture).*
