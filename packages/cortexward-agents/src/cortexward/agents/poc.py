"""PoC agent (MPS §13, Verification Ladder rung 3): finding -> `EXPLOIT_POC` evidence.

This is the agent that closes the detect -> verify -> *exploit* loop. Given an
exploitable finding, it asks the model to write a proof-of-concept, runs that
PoC inside an isolated `SandboxPort`, and — only when the PoC demonstrably
triggers the vulnerability — attaches supporting `EXPLOIT_POC` evidence at the
`DYNAMIC_POC` rung. That rung (3) is `>= TAINT_CONFIRMED` (2), so on its own it
is the first evidence in this framework strong enough to carry a finding to
`FindingState.VERIFIED`, which is exactly what unblocks `RepairAgent` downstream
(it only patches verified findings).

**Trigger detection is a genuine positive proof.** The model is told to craft its
exploit so that `echo <marker>` runs *only* as a side effect of the vulnerable
code executing, where `<marker>` is a fresh, unguessable token minted per finding.
If that marker shows up in the sandbox's stdout/stderr, injected input provably
reached a command interpreter through the target's own code — a real exploit, not
a pattern match. The marker's unpredictability is what stops the target's normal
output (or a malicious target) from faking a success.

**One-directional, like every other signal in this framework.** Evidence is
attached *only* on a positive trigger. A PoC that runs without triggering the
marker, an unparseable PoC response, a path that escapes the target root, or any
sandbox infrastructure failure/timeout all attach *nothing* — never a refutation.
A failed PoC most often means the model wrote a weak exploit, not that the code is
safe, so treating it as evidence of safety would wrongly de-escalate real bugs
(the same reason `is_reachable_from_entrypoint` returning `False` never means
"proven unreachable").

**Deliberately narrow.** Only findings whose CWE is in `POC_SUPPORTED_CWES` are
attempted — OS command injection (CWE-78) first, the most mechanically verifiable
class (inject a marker-echoing command, look for the marker). Everything else is
skipped untouched. Widening the exploitable-class set, and bundling more than the
finding's own file for cross-file targets (Milestone 1), are future work, not a
silent gap.
"""

from __future__ import annotations

import re
import tarfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from cortexward.agents.prompt_loader import load_prompt
from cortexward.agents.state import RunState
from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingState,
    Provenance,
    VerificationRung,
    apply_assessment,
)
from cortexward.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    ExecutionSpec,
    LLMPort,
    SandboxPort,
)

_PROMPT = load_prompt("poc", "v1")

# CWE classes this agent knows how to build a marker-based PoC for. Command
# injection (CWE-78) is the one class where "the exploit succeeded" has a clean,
# unambiguous dynamic signal: an injected `echo <marker>` either runs or it
# doesn't. SQLi/SSRF/deserialization need a live DB / listener / gadget in the
# sandbox and a subtler success oracle — separate slices, not this one.
POC_SUPPORTED_CWES: frozenset[int] = frozenset({78})

# Findings the Verifier already settled negatively (or that are already fixed):
# spending a sandbox run on them buys nothing.
_SKIP_STATES: frozenset[FindingState] = frozenset(
    {FindingState.REFUTED, FindingState.DISMISSED, FindingState.PATCHED}
)

_POC_FILENAME = "poc.py"


@runtime_checkable
class ArtifactSink(Protocol):
    """The one method this agent needs to hand a bundle to the sandbox.

    A narrow structural protocol (not an import of `cortexward.ports.StoragePort`):
    the PoC bundle is stored via `put_artifact`, and the `SandboxPort` this agent
    is wired to reads it back by the same reference from the *same* store. Any
    real `StoragePort` satisfies this structurally, with no glue code.
    """

    def put_artifact(self, content: bytes) -> str: ...


@runtime_checkable
class ArtifactStore(ArtifactSink, Protocol):
    """`ArtifactSink` plus read-back — what Gate D needs to fetch a stored PoC."""

    def get_artifact(self, ref: str) -> bytes: ...


# A markdown code block: ```lang\n...``` — closing fence optional (matched to
# end of string) since models occasionally omit it.
_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)(?:```|\Z)", re.DOTALL)


def _parse_poc(text: str) -> str | None:
    """Extract the PoC script from a model response.

    Robust to how real models actually answer, not just the literal format the
    prompt asks for: an explicit ``POC:`` section is honoured if present, but a
    plain fenced code block (what models return most of the time — verified
    against `qwen2.5-coder:7b`, which drops the ``POC:`` prefix and just emits a
    ```python block) is accepted too. A response that is neither — prose, a
    refusal — yields ``None`` (inconclusive), so we never bundle and run
    non-code as if it were a PoC.
    """
    had_marker = "POC:" in text
    body = text.partition("POC:")[2] if had_marker else text
    match = _FENCE.search(body)
    if match:
        return match.group(1).strip() or None
    if had_marker:
        return body.strip() or None
    return None


class PocAgent:
    """Generates and runs a sandboxed PoC, attaching `EXPLOIT_POC` evidence on success."""

    name = "poc"

    def __init__(
        self,
        *,
        llm: LLMPort,
        sandbox: SandboxPort,
        artifacts: ArtifactSink,
        root: Path,
        marker_factory: Callable[[], str] | None = None,
    ) -> None:
        self._llm = llm
        self._sandbox = sandbox
        self._artifacts = artifacts
        self._root = Path(root)
        self._marker_factory = marker_factory or (lambda: f"CORTEXWARD_POC_{uuid4().hex}")

    def run(self, state: RunState) -> RunState:
        results = tuple(self._verify_one(finding) for finding in state.findings)
        verified = sum(
            1
            for before, after in zip(state.findings, results, strict=True)
            if len(after.evidence) > len(before.evidence)
        )
        note = f"proof-of-concept verified {verified} finding(s)"
        return state.with_findings(results).with_note(self.name, note).with_completed(self.name)

    def _verify_one(self, finding: Finding) -> Finding:
        if finding.cwe not in POC_SUPPORTED_CWES:
            return finding
        if finding.state in _SKIP_STATES:
            return finding
        if not finding.locations:
            return finding
        evidence = self._attempt_poc(finding)
        if evidence is None:
            return finding
        return apply_assessment(finding.with_evidence(evidence))

    def _attempt_poc(self, finding: Finding) -> Evidence | None:
        location = finding.locations[0]
        source = self._read_source(location.path)
        if source is None:
            return None

        marker = self._marker_factory()
        prompt = _PROMPT.render(
            rule_id=finding.rule_id,
            cwe=finding.cwe,
            message=finding.message,
            location=str(location),
            path=location.path,
            marker=marker,
            source=source,
        )
        result = self._llm.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content=prompt),))
        )
        poc_code = _parse_poc(result.text or "")
        if poc_code is None:
            return None

        triggered = run_poc_in_sandbox(
            relative=location.path,
            source=source,
            poc_code=poc_code,
            marker=marker,
            sandbox=self._sandbox,
            artifacts=self._artifacts,
        )
        if triggered is not True:
            # None (infra failure/timeout) or False (ran, no trigger) are both
            # "no positive proof" -- one-directional, never a refutation.
            return None
        # Stash the exact PoC + marker so Gate D can re-run *this* exploit
        # against the patched code (MPS §16, "original PoC neutralized").
        poc_ref = self._artifacts.put_artifact(poc_code.encode("utf-8"))
        return Evidence(
            kind=EvidenceKind.EXPLOIT_POC,
            rung=VerificationRung.DYNAMIC_POC,
            supports=True,
            summary="proof-of-concept executed in the sandbox; injected marker observed in output",
            provenance=Provenance(producer=self.name, model=self._llm.model_id),
            artifact_ref=poc_ref,
            data={"poc_marker": marker, "poc_path": location.path},
        )

    def _read_source(self, relative: str) -> str | None:
        """Read the finding's own file, refusing any path that escapes the target root.

        The location path is scanner-produced from analyzed (untrusted) input
        (ADR-0004); resolving it and confirming it stays under `root` before
        reading stops a crafted path from pulling an unrelated host file into a
        bundle. Returns `None` (inconclusive) on anything that isn't a real file
        inside the root.
        """
        root = self._root.resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        return candidate.read_text(encoding="utf-8", errors="replace")


def run_poc_in_sandbox(
    *,
    relative: str,
    source: str,
    poc_code: str,
    marker: str,
    sandbox: SandboxPort,
    artifacts: ArtifactSink,
) -> bool | None:
    """Bundle `{source at relative + poc.py}`, run `poc.py` in the sandbox, and
    report whether the exploit triggered.

    Returns `True` if `marker` appeared in the sandbox's stdout/stderr (the
    exploit fired), `False` if the PoC ran to completion without it (ran, did
    not trigger), or `None` if the run was inconclusive — a sandbox
    infrastructure failure (e.g. no Docker daemon) or a timeout, neither of
    which is evidence either way. Shared by `PocAgent` (positive proof on
    `True`) and Gate D (`False` on the *patched* code means neutralized).
    """
    bundle = _bundle(relative, source, poc_code)
    ref = artifacts.put_artifact(bundle)
    try:
        outcome = sandbox.execute(
            ExecutionSpec(command=("python", _POC_FILENAME), input_bundle_ref=ref)
        )
    except Exception:
        return None
    if outcome.timed_out:
        return None
    return marker in outcome.stdout or marker in outcome.stderr


def _bundle(relative: str, source: str, poc_code: str) -> bytes:
    """A tar of the finding's file (at its relative path) plus `poc.py` at the root.

    The sandbox unpacks this into `/workspace` and runs `python poc.py` there, so
    the PoC loads the target via `relative` and the two sit side by side.
    Only the finding's own file is bundled — enough for a single-file
    exploitable target; cross-file bundling waits on cross-file taint (Milestone 1).
    """
    # ponytail: single-file bundle; widen to the whole root once cross-file taint lands.
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in ((relative.replace("\\", "/"), source), (_POC_FILENAME, poc_code)):
            encoded = data.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(encoded)
            tar.addfile(info, BytesIO(encoded))
    return buffer.getvalue()


__all__ = [
    "POC_SUPPORTED_CWES",
    "ArtifactSink",
    "ArtifactStore",
    "PocAgent",
    "run_poc_in_sandbox",
]
