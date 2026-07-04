# 002 — VEX as a first-class output

**Status:** planned (Phase 6 output; schema in domain now)
**Theme:** standards alignment, exploitability communication

## Problem

Security tooling floods teams with findings but rarely answers the question that actually
governs action: *is this exploitable in my context?* SARIF communicates findings; it does not
communicate exploitability decisions in a machine-consumable, standardized way.

## Insight

**VEX (Vulnerability Exploitability eXchange)** — as standardized by CycloneDX and CSAF — is
precisely the standardized form of the question the Verification Ladder answers. Statuses like
`not_affected` (with a justification such as "code not reachable") and `affected` (with an
attached PoC) map directly onto ladder outcomes.

Emitting VEX is a differentiator: mainstream AI code reviewers lead with findings, not with
exploitability verdicts. AegisForge can make VEX a primary, first-class output.

## Approach

- Derive VEX status from the assessment (`aegisforge.domain.verification` already computes
  `VexStatus`): refutation → `not_affected`; PoC/differential at high confidence → `affected`;
  validated patch → `fixed`; otherwise `under_investigation`.
- Emit CycloneDX-VEX and CSAF-VEX documents alongside SARIF and a CycloneDX SBOM.
- Attach machine-readable **justifications** grounded in the evidence (e.g. reachability proof
  artifact) so downstream consumers can audit the claim.

## Evaluation ideas

- **Actionability study.** Do VEX verdicts reduce triage time vs. raw findings? (Human study.)
- **Interoperability.** Validate emitted documents against CycloneDX/CSAF schemas; round-trip
  through common consumers.
- **Agreement.** Compare AegisForge `not_affected` verdicts against expert judgments and
  against reachability ground truth.

## Open questions

- Which VEX justification vocabulary entries can we support with automated evidence, and which
  require human sign-off?
- How do we express *confidence* in a VEX ecosystem that is largely binary?

## Related

- Builds on: [001 — The Verification Ladder](001-verification-ladder.md)
- Schema: `VexStatus` in [`aegisforge/domain/enums.py`](../src/aegisforge/domain/enums.py)
