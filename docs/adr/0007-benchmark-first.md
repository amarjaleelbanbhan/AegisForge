# ADR-0007: Benchmark-first roadmap ordering

**Status:** Accepted · **Date:** 2026-07-05 · **Reorders the roadmap**

## Context
The original roadmap placed benchmarks at Phase 9. Building autonomous agents before the
measurement harness means months of unmeasured work, hidden regressions, and weak research claims.
The mandate is explicit: every feature must move a measured metric.

## Decision
Build the **evaluation harness + a golden dataset + the `RunManifest`** in **Phase 3.5**,
immediately after scanners and *before* the heavy agent work of Phase 4. From Phase 3.5 onward,
every phase reports metric deltas on the benchmark; CI gates PRs on no-regression of primary
metrics (fast smoke suite).

## Consequences
- Every capability is measurable from the moment it exists; regressions are caught.
- Research claims are reproducible and artifact-evaluation ready.
- Some upfront investment in the harness before the "exciting" agent work — accepted deliberately.

## Alternatives considered
- **Benchmark last (original plan).** Rejected: unmeasured development, weak evidence.
- **Ad-hoc metrics per feature.** Rejected: not comparable or reproducible.

*Specified in [MPS §23](../specifications/MPS-v1.0.md#23-benchmark--evaluation) and the
[Evaluation Framework](../benchmark/evaluation-framework.md).*
