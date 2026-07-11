"""Memory agent (MPS §13): reads/writes triage decisions via `RepositoryMemory` (MPS §15 tier 2).

Retrieval only — never trains on findings, never bypasses
`cortexward.domain.verification`'s assessment gate. Two effects, applied
every run:

1. Findings already suppressed from a previous run (by fingerprint) are
   marked `FindingState.DISMISSED`, so a known false positive doesn't need
   re-triage every scan.
2. Findings this run's Verifier refuted are persisted as new suppressions,
   so future runs recognize them without spending another LLM call.
"""

from __future__ import annotations

from cortexward.agents.memory import RepositoryMemory, fingerprint_for
from cortexward.agents.state import RunState
from cortexward.domain import Finding, FindingState


class MemoryAgent:
    """Applies and updates repository-level suppression memory for this run's findings."""

    name = "memory"

    def __init__(self, *, repository_memory: RepositoryMemory) -> None:
        self._memory = repository_memory

    def run(self, state: RunState) -> RunState:
        updated: list[Finding] = []
        dismissed = 0
        persisted = 0
        for original in state.findings:
            fingerprint = fingerprint_for(original)
            already_suppressed = self._memory.is_suppressed(fingerprint)
            if original.state != FindingState.DISMISSED and already_suppressed:
                updated.append(original.with_state(FindingState.DISMISSED))
                dismissed += 1
                continue
            if original.state == FindingState.REFUTED and not already_suppressed:
                self._memory.record_suppression(fingerprint, reason=original.message)
                persisted += 1
            updated.append(original)
        note = f"{dismissed} dismissed from memory; {persisted} new suppression(s) recorded"
        state = state.with_findings(tuple(updated))
        return state.with_note(self.name, note).with_completed(self.name)


__all__ = ["MemoryAgent"]
