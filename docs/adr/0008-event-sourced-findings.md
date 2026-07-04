# ADR-0008: Event-sourced findings with materialized state

**Status:** Accepted · **Date:** 2026-07-05

## Context
A finding *evolves* as evidence accrues (detected → corroborated → verified → patched). Storing it
as a mutable row loses history and undermines reproducibility and audit — both headline goals. The
domain core already updates findings functionally (`with_evidence`, `with_state`).

## Decision
Persist findings as an **append-only event log** (`FindingDetected`, `EvidenceAttached`,
`Assessed`, `PatchProposed`, `Suppressed`, …) with the current state as a **materialized read
model**, behind `StoragePort`. Reference adapters: SQLite (local) and Postgres+pgvector (server).
Artifacts (PoCs, SARIF, diffs) live in a content-addressed object store. The domain model never
imports ORM/storage types.

## Consequences
- Reproducibility, audit, and time-travel come for free; matches the functional core.
- Suppressions and triage decisions naturally join the log (feeds memory).
- More design care than CRUD; read models must be rebuilt from events on schema change.

## Alternatives considered
- **CRUD over mutable rows.** Rejected: loses evidence history and provenance.
- **Full external event-store dependency.** Rejected: unnecessary weight; a simple append table
  suffices behind the port.

*Specified in [MPS §18–19](../specifications/MPS-v1.0.md#18-event-flow--data-flow).*
