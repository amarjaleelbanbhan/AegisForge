"""Verifier agent (MPS §13): finding -> evidence up the ladder.

LLM-only verification is intentionally bounded by the domain's own
LLM-insufficiency policy (`cortexward.domain.verification`): attaching an
`LLM_ASSESSMENT` `Evidence` can move a finding from `CANDIDATE` to
`TRIAGED` (or down to `REFUTED`, if the model reports `FALSE_POSITIVE`),
but confidence built from `LLM_ASSESSMENT` evidence alone is capped below
`VERIFIED_THRESHOLD`, so this agent can never singlehandedly mark a finding
`VERIFIED` from LLM judgement alone.

When a `CodeGraph` is available for a finding's location (built by
`cortexward.agents.code_graphs.build_code_graphs` and passed in), this
agent also attaches independent `REACHABILITY_PROOF` evidence — the first
piece of evidence in this v1 framework that isn't LLM judgement. On its
own it's enough to raise a finding from `CANDIDATE` to `TRIAGED`; combined
with a supporting LLM verdict it raises confidence further still, but not
as far as `VERIFIED_THRESHOLD` — reaching `VERIFIED` needs a stronger
independent signal (taint trace, PoC, differential test) this v1 framework
doesn't produce yet. This is deliberately one-directional: a finding whose
location isn't reachable from any known entrypoint is *not* treated as
refuted — the graph's entrypoint detection is a narrow heuristic (the
Python `_ast_walker` marks only `main()` and `if __name__ == "__main__":`
guards today), so "not proven reachable by this heuristic" is not the same
claim as "proven unreachable." Only a genuine positive proof is ever
attached.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    Provenance,
    VerificationRung,
    apply_assessment,
)
from cortexward.ports import ChatMessage, ChatRole, CodeGraph, CompletionRequest, LLMPort

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

    def __init__(self, *, llm: LLMPort, code_graphs: Mapping[str, CodeGraph] | None = None) -> None:
        self._llm = llm
        self._code_graphs = code_graphs or {}

    def run(self, state: RunState) -> RunState:
        updated = tuple(self._verify_one(finding) for finding in state.findings)
        note = f"verified {len(updated)} finding(s)"
        return state.with_findings(updated).with_note(self.name, note).with_completed(self.name)

    def _verify_one(self, finding: Finding) -> Finding:
        reachability_evidence = self._reachability_evidence(finding)
        if reachability_evidence is not None:
            finding = finding.with_evidence(reachability_evidence)

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
            if reachability_evidence is None:
                return finding
            return apply_assessment(finding)

        llm_evidence = Evidence(
            kind=EvidenceKind.LLM_ASSESSMENT,
            supports=verdict == "REAL",
            summary=reason,
            provenance=Provenance(producer=self.name, model=self._llm.model_id),
        )
        return apply_assessment(finding.with_evidence(llm_evidence))

    def _reachability_evidence(self, finding: Finding) -> Evidence | None:
        for location in finding.locations:
            for graph in self._code_graphs.values():
                entrypoints = graph.entrypoints()
                if not entrypoints:
                    continue
                nodes = graph.nodes_at(location.path, location.start_line)
                if not nodes:
                    continue
                # A source location resolves to several overlapping graph
                # nodes (statement, call, sub-expressions, ...), but the CFG
                # builder only links statement-level nodes into its
                # CFG_NEXT chain -- an inner call/expression node this same
                # line also resolves to is often simply absent from that
                # chain. Check every candidate rather than just the most
                # specific one: reachability is a positive-proof query, so
                # any one of them proving a path is a genuine proof.
                if any(graph.reachable(list(entrypoints), node) for node in nodes):
                    return Evidence(
                        kind=EvidenceKind.REACHABILITY_PROOF,
                        rung=VerificationRung.STATIC_REACHABILITY,
                        supports=True,
                        summary=(
                            f"reachable from {len(entrypoints)} known entrypoint(s) "
                            "via control flow"
                        ),
                        provenance=Provenance(producer=self.name),
                    )
        return None


__all__ = ["VerifierAgent"]
