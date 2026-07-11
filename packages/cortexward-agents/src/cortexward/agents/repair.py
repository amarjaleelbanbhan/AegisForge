"""Repair agent (MPS §13): verified finding -> candidate patch (minimal diff).

Only findings the Verifier already moved to `FindingState.VERIFIED` get a
patch proposal — matching MPS §13's "Repair: verified finding -> candidate
patch." A patch this agent produces is a *candidate* only:
`Patch.is_validated` requires the three-gate checks (tests pass, rescan
clean, exploit neutralized) MPS §16 defines, none of which this agent
performs.
"""

from __future__ import annotations

import re

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import Finding, FindingState, Patch, Provenance
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort

_PROMPT = load_prompt("repair", "v1")
_DIFF_FILE_PATTERN = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def _parse_repair(text: str) -> tuple[str, str] | None:
    if "DIFF:" not in text:
        return None
    description_part, _, diff_part = text.partition("DIFF:")
    description = description_part.replace("DESCRIPTION:", "", 1).strip()
    diff = diff_part.strip()
    if not description or not diff:
        return None
    return description, diff


class RepairAgent:
    """Proposes a minimal-diff patch for each verified finding."""

    name = "repair"

    def __init__(self, *, llm: LLMPort) -> None:
        self._llm = llm

    def run(self, state: RunState) -> RunState:
        patches: list[Patch] = []
        skipped = 0
        for finding in state.findings:
            if finding.state != FindingState.VERIFIED:
                continue
            patch = self._repair_one(finding)
            if patch is None:
                skipped += 1
            else:
                patches.append(patch)
        note = f"proposed {len(patches)} patch(es); {skipped} unparseable repair response(s)"
        return (
            state.with_patches(tuple(patches)).with_note(self.name, note).with_completed(self.name)
        )

    def _repair_one(self, finding: Finding) -> Patch | None:
        location = str(finding.locations[0]) if finding.locations else "unknown location"
        prompt = _PROMPT.render(
            rule_id=finding.rule_id,
            cwe=finding.cwe if finding.cwe is not None else "unknown",
            message=finding.message,
            location=location,
        )
        result = self._llm.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content=prompt),))
        )
        parsed = _parse_repair(result.text or "")
        if parsed is None:
            return None
        description, diff = parsed
        files_changed = tuple(_DIFF_FILE_PATTERN.findall(diff))
        return Patch(
            finding_id=finding.id,
            diff=diff,
            description=description,
            files_changed=files_changed,
            provenance=Provenance(producer=self.name, model=self._llm.model_id),
        )


__all__ = ["RepairAgent"]
