"""Coordinator agent (MPS §13): orchestrates, enforces budgets, dedup; owns RunState transitions.

Budget enforcement and dedup already live elsewhere in this v1 agent
framework (`correlate()` dedups at Scanner time; `ResilientLLM`/
`run_tool_loop` own retry/iteration budgets) — this agent's job is the one
thing nothing else does: producing a factual, audited run summary as the
final `RunState` note before the pipeline ends.
"""

from __future__ import annotations

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import FindingState
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort

_PROMPT = load_prompt("coordinator", "v1")


class CoordinatorAgent:
    """Summarizes the run's outcome (findings/verified/false-positives/patches) as a final note."""

    name = "coordinator"

    def __init__(self, *, llm: LLMPort) -> None:
        self._llm = llm

    def run(self, state: RunState) -> RunState:
        verified_count = sum(
            1 for finding in state.findings if finding.state == FindingState.VERIFIED
        )
        false_positive_count = sum(
            1 for finding in state.findings if finding.state == FindingState.REFUTED
        )
        prompt = _PROMPT.render(
            finding_count=len(state.findings),
            verified_count=verified_count,
            false_positive_count=false_positive_count,
            patch_count=len(state.patches),
        )
        result = self._llm.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content=prompt),))
        )
        note = result.text or "(coordinator produced no summary text)"
        return state.with_note(self.name, note).with_completed(self.name).with_round_complete()


__all__ = ["CoordinatorAgent"]
