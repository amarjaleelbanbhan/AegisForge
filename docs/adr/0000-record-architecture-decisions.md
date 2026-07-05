# ADR-0000: Record architecture decisions

**Status:** Accepted · **Date:** 2026-07-05

## Context
CortexWard is a long-lived, multi-contributor platform. Decisions made implicitly are forgotten,
re-litigated, and eroded. Once the MPS is approved, the architecture must be stable yet able to
evolve deliberately.

## Decision
We record significant architecture decisions as ADRs in `docs/adr/`, using the Nygard format.
After MPS approval, the architecture is frozen: it changes only through new ADRs that supersede
prior ones. The MPS references ADRs as the mechanism for its own amendment.

## Consequences
- A durable, greppable history of *why* the system is shaped as it is.
- Changes are deliberate and reviewable, not incidental.
- Small overhead per decision — accepted as the cost of maintainability.

## Alternatives considered
- **No ADRs / decisions in PRs only.** Rejected: not discoverable, easily lost.
- **A single evolving design doc.** Rejected: no clear supersession trail or freeze point.
