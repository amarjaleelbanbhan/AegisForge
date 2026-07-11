"""Reviewer agent (MPS §13): advisory LLM review of a proposed patch.

This agent is deliberately **not** one of the three-gate validators
(`Patch.tests_pass` / `rescan_clean` / `exploit_neutralized`) MPS §16
requires before a patch is considered `Patch.is_validated` — those gates
need real test execution, a rescan, and sandboxed exploit replay, none of
which an LLM opinion can honestly stand in for (the same LLM-insufficiency
policy `cortexward.domain.verification` enforces for findings). This
agent's verdict is recorded as a `RunState` note only; it never sets a
`Patch` gate field.
"""

from __future__ import annotations

import re

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import Finding, Patch
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort

_PROMPT = load_prompt("reviewer", "v1")
_REVIEW_PATTERN = re.compile(r"REVIEW:\s*(APPROVE|REJECT|NEEDS_CHANGES)\s*-\s*(.+)", re.IGNORECASE)


def _parse_review(text: str) -> tuple[str, str]:
    match = _REVIEW_PATTERN.search(text)
    if match is None:
        return "NEEDS_CHANGES", text.strip() or "no parseable review"
    return match.group(1).upper(), match.group(2).strip()


class ReviewerAgent:
    """Records an advisory APPROVE/REJECT/NEEDS_CHANGES verdict for each patch as a run note."""

    name = "reviewer"

    def __init__(self, *, llm: LLMPort) -> None:
        self._llm = llm

    def run(self, state: RunState) -> RunState:
        findings_by_id = {finding.id: finding for finding in state.findings}
        updated_state = state
        for patch in state.patches:
            verdict, reason = self._review_one(patch, findings_by_id.get(patch.finding_id))
            note = f"{patch.id}: {verdict} - {reason}"
            updated_state = updated_state.with_note(self.name, note)
        return updated_state.with_completed(self.name)

    def _review_one(self, patch: Patch, finding: Finding | None) -> tuple[str, str]:
        finding_summary = (
            finding.message if finding is not None else "(finding not found in this run)"
        )
        prompt = _PROMPT.render(
            finding_summary=finding_summary,
            patch_description=patch.description,
            patch_diff=patch.diff,
        )
        result = self._llm.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content=prompt),))
        )
        return _parse_review(result.text or "")


__all__ = ["ReviewerAgent"]
