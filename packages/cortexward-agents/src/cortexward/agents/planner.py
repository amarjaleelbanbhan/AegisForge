"""Planner agent (MPS §13): target -> plan (languages, scanners, budget).

The Planner doesn't itself choose which `ScannerPort` instances run — that's
constructor-time wiring on `ScannerAgent`. Its job is to record a
human/audit-readable rationale for the run before scanning starts, per MPS
§13's "target -> plan (which languages, scanners, budget)".
"""

from __future__ import annotations

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort

_PROMPT = load_prompt("planner", "v1")


class PlannerAgent:
    """Renders the planner prompt and records the model's plan as a run note."""

    name = "planner"

    def __init__(self, *, llm: LLMPort) -> None:
        self._llm = llm

    def run(self, state: RunState) -> RunState:
        languages = ", ".join(state.request.languages) if state.request.languages else "auto-detect"
        prompt = _PROMPT.render(root=str(state.request.root), languages=languages)
        result = self._llm.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content=prompt),))
        )
        note = result.text or "(planner produced no plan text)"
        return state.with_note(self.name, note).with_completed(self.name)


__all__ = ["PlannerAgent"]
