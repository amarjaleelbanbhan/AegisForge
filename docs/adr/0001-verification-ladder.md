# ADR-0001: Verification Ladder over binary exploitation

**Status:** Accepted · **Date:** 2026-07-05

## Context
The research brief proposed confirming every finding by generating and running an exploit. That
only works for script-exploitable classes (injection, SSRF, deserialization) and cannot confirm
missing-authorization, weak-crypto, or race conditions. Binary "exploited or not" also throws away
weaker-but-real evidence.

## Decision
Model verification as a **ladder of increasingly strong evidence**
(`NONE → STATIC_REACHABILITY → TAINT_CONFIRMED → DYNAMIC_POC → DIFFERENTIAL_TEST`) and calibrate a
confidence per finding from the evidence gathered, in log-odds space. Report the *strongest
feasible* rung per vulnerability class (per-CWE ceilings). Two policies are structural: an LLM
alone cannot climb the ladder or verify a finding; refutation is first-class negative evidence.

## Consequences
- Covers all CWE classes; a stronger, more honest, publishable research claim.
- Explainable, monotonic confidence; drives lifecycle state and VEX status.
- Requires a `CalibrationProfile` and per-CWE ceiling mapping (tracked as open question).

## Alternatives considered
- **Binary exploit-only.** Rejected: narrow coverage, discards partial evidence.
- **LLM-confidence-only.** Rejected: unverifiable, hallucination-prone.

*Implemented in `cortexward.domain.verification`. Specified in
[MPS §11](../specifications/MPS-v1.0.md#11-verification-ladder-specification).*
