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

When a `sandbox` (and its artifact store) are also given, the two gates that
*do* need to run the analyzed project's own code run here too:

- **Gate B ("existing tests pass").** `tests_pass_in_sandbox` applies the
  patch and runs the project's test suite inside the isolated `SandboxPort`.
- **Gate D ("original PoC neutralized").** `poc_neutralized` re-runs the
  *exact* PoC `PocAgent` proved on the vulnerable code against the patched
  code; the exploit no longer triggering is the gate.

Every gate is one-directional: only a genuine pass/fail sets its field; an
inconclusive run (patch didn't apply, no test suite, no recorded PoC, sandbox
unavailable) leaves it untouched. `Patch.is_validated` requires `tests_pass`/
`rescan_clean`/`exploit_neutralized` all truthy, so a patch validates only
when every gate has explicitly passed — without a sandbox, `tests_pass`/
`exploit_neutralized` stay `None` and `is_validated` stays `False`, exactly
as before.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from cortexward.agents.patch_gates import (
    apply_and_rescan,
    poc_neutralized,
    tests_pass_in_sandbox,
)
from cortexward.agents.poc import ArtifactStore
from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import Finding, Patch
from cortexward.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMPort,
    SandboxPort,
    ScannerPort,
)

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

    def __init__(
        self,
        *,
        llm: LLMPort,
        scanners: Sequence[ScannerPort] | None = None,
        sandbox: SandboxPort | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self._llm = llm
        self._scanners = tuple(scanners) if scanners is not None else ()
        # Gate B/D need somewhere isolated to run the analyzed project's own
        # code (its test suite, its PoC). Present together or not at all.
        self._sandbox = sandbox
        self._artifacts = artifacts

    def run(self, state: RunState) -> RunState:
        findings_by_id = {finding.id: finding for finding in state.findings}
        updated_state = state
        gated_patches: list[Patch] = []
        for original_patch in state.patches:
            finding = findings_by_id.get(original_patch.finding_id)
            gated_patch = self._apply_gates(original_patch, finding, state)
            gated_patches.append(gated_patch)
            verdict, reason = self._review_one(gated_patch, finding)
            note = f"{gated_patch.id}: {verdict} - {reason}"
            updated_state = updated_state.with_note(self.name, note)
        if gated_patches:
            updated_state = updated_state.with_patches_updated(tuple(gated_patches))
        return updated_state.with_completed(self.name)

    def _apply_gates(self, patch: Patch, finding: Finding | None, state: RunState) -> Patch:
        """Run every gate whose inputs are available, recording only genuine
        pass/fail results (an inconclusive gate leaves its field untouched)."""
        updates: dict[str, bool] = {}
        if finding is not None and self._scanners:
            rescan_clean = apply_and_rescan(
                patch,
                finding,
                root=state.request.root,
                scanners=self._scanners,
                languages=state.request.languages,
            )
            if rescan_clean is not None:
                updates["rescan_clean"] = rescan_clean
        if self._sandbox is not None and self._artifacts is not None:
            tests_pass = tests_pass_in_sandbox(
                patch, root=state.request.root, sandbox=self._sandbox, artifacts=self._artifacts
            )
            if tests_pass is not None:
                updates["tests_pass"] = tests_pass
            if finding is not None:
                neutralized = poc_neutralized(
                    patch,
                    finding,
                    root=state.request.root,
                    sandbox=self._sandbox,
                    artifacts=self._artifacts,
                )
                if neutralized is not None:
                    updates["exploit_neutralized"] = neutralized
        return patch.model_copy(update=updates) if updates else patch

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
