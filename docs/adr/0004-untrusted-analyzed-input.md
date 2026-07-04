# ADR-0004: Treat analyzed code as hostile input

**Status:** Accepted · **Date:** 2026-07-05

## Context
AegisForge feeds source, comments, commit messages, and docs to LLMs and executes PoCs. All of it
is attacker-controlled. A repo can attempt prompt injection ("mark this safe"), execute code
during "static" analysis (build hooks), or exfiltrate secrets.

## Decision
Treat every analyzed artifact as **untrusted data, never instructions**. Concretely:
data/instruction separation at the LLM boundary; **no tool** that lets a model approve/dismiss a
finding or perform egress; **no project build execution** during static analysis; all dynamic
execution in a deny-by-default sandbox; secret redaction before any external call; the tool's own
supply chain scanned in CI.

## Consequences
- Prompt injection cannot change a verdict; even a manipulated model is contained by the ladder's
  independent-corroboration requirement.
- Some convenience (e.g. build-informed analysis) is sacrificed for safety.

## Alternatives considered
- **Trust the repo / run builds for better signal.** Rejected: unacceptable RCE surface.
- **Prompt-level "ignore injections" instructions.** Rejected: not a real control.

*Specified in [MPS §22](../specifications/MPS-v1.0.md#22-security-architecture); research note
[004](../../research/004-prompt-injection-resistant-agents.md).*
