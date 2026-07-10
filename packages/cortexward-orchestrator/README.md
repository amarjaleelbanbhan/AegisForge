# cortexward-orchestrator

`OrchestratorPort` implementations for
[CortexWard](https://github.com/amarjaleelbanbhan/CortexWard) (MPS §13, ADR-0002).

Ships `SequentialOrchestrator`: runs every configured scanner, then normalizes and correlates
their results into `Finding`s via `cortexward.scanners.correlate`. No LLM or agent reasoning yet
— the reference in-process orchestrator that "run every scanner and merge the results" needs
before any agent-driven planning/verification/repair (later Phase 4 work) enters the picture.
