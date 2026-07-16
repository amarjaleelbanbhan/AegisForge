"""Reviewer agent (MPS §13): gate verdicts and advisory LLM review for a proposed patch.

Two different kinds of verdict, kept structurally distinct:

- **Real gate verification.** When `scanners` is given, this agent runs
  `cortexward.agents.patch_gates.apply_and_rescan` for each patch — Gate A
  ("applies cleanly") and Gate C ("rescan clean") from MPS §16's patch
  pipeline, neither of which needs sandboxed code execution. Only a
  genuine positive/negative rescan result ever sets `Patch.rescan_clean`;
  an inconclusive outcome (patch didn't apply, files missing, `git`
  unavailable, ...) leaves it untouched rather than guessing.
- **Advisory LLM review.** A free-text APPROVE/REJECT/NEEDS_CHANGES
  verdict is recorded as a `RunState` note only — it never sets a `Patch`
  gate field. An LLM opinion can't honestly stand in for a gate (the same
  LLM-insufficiency policy `cortexward.domain.verification` enforces for
  findings).

`Patch.is_validated` still requires `tests_pass`/`rescan_clean`/
`exploit_neutralized` all truthy — Gate B ("existing tests pass") and Gate D
("original PoC neutralized") need to run the analyzed project's own code,
which needs Phase 6's `SandboxPort` and doesn't exist yet, so `tests_pass`/
`exploit_neutralized` are never set here. A patch can reach `rescan_clean =
True` through this agent and still correctly have `is_validated = False`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from cortexward.agents.patch_gates import apply_and_rescan
from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import Finding, Patch
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort, ScannerPort

_PROMPT = load_prompt("reviewer", "v1")
_REVIEW_PATTERN = re.compile(r"REVIEW:\s*(APPROVE|REJECT|NEEDS_CHANGES)\s*-\s*(.+)", re.IGNORECASE)


def _parse_review(text: str) -> tuple[str, str]:
    match = _REVIEW_PATTERN.search(text)
    if match is None:
        return "NEEDS_CHANGES", text.strip() or "no parseable review"
    return match.group(1).upper(), match.group(2).strip()


class ReviewerAgent:
    """Verifies each patch's rescan-clean gate (if `scanners` given) and records an advisory
    verdict."""

    name = "reviewer"

    def __init__(self, *, llm: LLMPort, scanners: Sequence[ScannerPort] | None = None) -> None:
        self._llm = llm
        self._scanners = tuple(scanners) if scanners is not None else ()

    def run(self, state: RunState) -> RunState:
        findings_by_id = {finding.id: finding for finding in state.findings}
        updated_state = state
        gated_patches: list[Patch] = []
        for original_patch in state.patches:
            finding = findings_by_id.get(original_patch.finding_id)
            gated_patch = self._apply_rescan_gate(original_patch, finding, state)
            gated_patches.append(gated_patch)
            verdict, reason = self._review_one(gated_patch, finding)
            note = f"{gated_patch.id}: {verdict} - {reason}"
            updated_state = updated_state.with_note(self.name, note)
        if gated_patches:
            updated_state = updated_state.with_patches_updated(tuple(gated_patches))
        return updated_state.with_completed(self.name)

    def _apply_rescan_gate(self, patch: Patch, finding: Finding | None, state: RunState) -> Patch:
        if finding is None or not self._scanners:
            return patch
        rescan_clean = apply_and_rescan(
            patch,
            finding,
            root=state.request.root,
            scanners=self._scanners,
            languages=state.request.languages,
        )
        if rescan_clean is None:
            return patch
        return patch.model_copy(update={"rescan_clean": rescan_clean})

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
