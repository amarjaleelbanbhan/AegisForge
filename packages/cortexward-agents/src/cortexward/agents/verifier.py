"""Verifier agent (MPS §13): finding -> evidence up the ladder.

LLM-only verification is intentionally bounded by the domain's own
LLM-insufficiency policy (`cortexward.domain.verification`): attaching an
`LLM_ASSESSMENT` `Evidence` can move a finding from `CANDIDATE` to
`TRIAGED` (or down to `REFUTED`, if the model reports `FALSE_POSITIVE`),
but confidence built from `LLM_ASSESSMENT` evidence alone is capped below
`VERIFIED_THRESHOLD`, so this agent can never singlehandedly mark a finding
`VERIFIED` — reaching that rung needs independent evidence
(reachability/taint/PoC/differential test) this v1 agent framework doesn't
produce yet.
"""

from __future__ import annotations

import re

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import Evidence, EvidenceKind, Finding, Provenance, apply_assessment
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort

_PROMPT = load_prompt("verifier", "v1")
_VERDICT_PATTERN = re.compile(
    r"VERDICT:\s*(REAL|FALSE_POSITIVE|UNCERTAIN)\s*-\s*(.+)", re.IGNORECASE
)


def _parse_verdict(text: str) -> tuple[str, str]:
    match = _VERDICT_PATTERN.search(text)
    if match is None:
        return "UNCERTAIN", text.strip() or "no parseable verdict"
    return match.group(1).upper(), match.group(2).strip()


class VerifierAgent:
    """Asks the model whether each finding looks real, and attaches the verdict as evidence."""

    name = "verifier"

    def __init__(self, *, llm: LLMPort) -> None:
        self._llm = llm

    def run(self, state: RunState) -> RunState:
        updated = tuple(self._verify_one(finding) for finding in state.findings)
        note = f"verified {len(updated)} finding(s)"
        return state.with_findings(updated).with_note(self.name, note).with_completed(self.name)

    def _verify_one(self, finding: Finding) -> Finding:
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
        verdict, reason = _parse_verdict(result.text or "")
        if verdict == "UNCERTAIN":
            return finding
        evidence = Evidence(
            kind=EvidenceKind.LLM_ASSESSMENT,
            supports=verdict == "REAL",
            summary=reason,
            provenance=Provenance(producer=self.name, model=self._llm.model_id),
        )
        return apply_assessment(finding.with_evidence(evidence))


__all__ = ["VerifierAgent"]
