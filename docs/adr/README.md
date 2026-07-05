# Architecture Decision Records (ADRs)

This directory holds CortexWard's architecture decisions. After the
[MPS v1.0](../specifications/MPS-v1.0.md) is approved, the architecture is **frozen**: any change
to a decision it records is made only by adding a new ADR here (which may supersede an earlier
one) and bumping the MPS version.

We use the lightweight [Michael Nygard ADR format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
Each ADR has a status: **Proposed · Accepted · Superseded by ADR-XXXX · Deprecated**.

## Process

1. Copy an existing ADR as `NNNN-short-title.md`, next number.
2. Fill in Context, Decision, Consequences, Alternatives.
3. Open a PR labeled `adr`. Significant ADRs follow governance lazy-consensus.
4. On merge, set status to **Accepted** and add it to the index below.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0000](0000-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0001](0001-verification-ladder.md) | Verification Ladder over binary exploitation | Accepted |
| [0002](0002-orchestration-in-process-behind-port.md) | In-process orchestration behind a port | Accepted |
| [0003](0003-standards-aligned-outputs.md) | SARIF + VEX + SBOM as first-class outputs | Accepted |
| [0004](0004-untrusted-analyzed-input.md) | Treat analyzed code as hostile input | Accepted |
| [0005](0005-uv-workspace-monorepo.md) | uv workspace monorepo with `cortexward.*` namespace | Accepted |
| [0006](0006-llm-provider-abstraction.md) | Own the LLM abstraction; providers are adapters | Accepted |
| [0007](0007-benchmark-first.md) | Benchmark-first roadmap ordering | Accepted |
| [0008](0008-event-sourced-findings.md) | Event-sourced findings with materialized state | Accepted |
