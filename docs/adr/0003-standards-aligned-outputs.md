# ADR-0003: SARIF + VEX + SBOM as first-class outputs

**Status:** Accepted · **Date:** 2026-07-05

## Context
Security tooling floods teams with findings but rarely answers the operative question: *is this
exploitable in my context?* SARIF communicates findings but not exploitability decisions.

## Decision
Emit **SARIF 2.1.0** (findings), **VEX** (CycloneDX-VEX / CSAF-VEX — exploitability), and
**CycloneDX SBOM** as first-class outputs, all carrying provenance and a `RunManifest` reference.
The internal `Finding` model is richer than SARIF and *exports* to these formats via `ReporterPort`
adapters.

## Consequences
- VEX is the standardized form of the exact question the Verification Ladder answers — a
  differentiator competitors do not lead with.
- Interoperability with existing security pipelines and code-scanning dashboards.
- Must track external schema versions in the `RunManifest`.

## Alternatives considered
- **SARIF only.** Rejected: no exploitability verdict channel.
- **Custom JSON only.** Rejected: no ecosystem interoperability.

*Specified in [MPS §20](../specifications/MPS-v1.0.md#20-api-contracts) and §23.*
