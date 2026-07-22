"""Unit tests for `ReviewerAgent`."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cortexward.agents import ReviewerAgent, RunState
from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    Patch,
    Provenance,
    SourceLocation,
    VerificationRung,
)
from cortexward.ports import (
    AnalysisRequest,
    CompletionRequest,
    CompletionResult,
    ExecutionResult,
    ExecutionSpec,
    TokenUsage,
)
from cortexward.scanners import BanditScanner

pytestmark = pytest.mark.unit


class _ScriptedLLM:
    def __init__(self, texts: list[str | None]) -> None:
        self.model_id = "fake-model"
        self._texts = list(texts)
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(
            text=self._texts.pop(0),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            model=self.model_id,
            stop_reason="end_turn",
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def cost_estimate(self, usage: TokenUsage) -> float:
        return 0.0


def _finding(rule_id: str = "R1") -> Finding:
    return Finding(
        rule_id=rule_id,
        title="t",
        message="SQL built from string concatenation",
        cwe=89,
        locations=(SourceLocation(path="app.py", start_line=3),),
        provenance=Provenance(producer="test"),
    )


def _patch(finding_id: str) -> Patch:
    return Patch(
        finding_id=finding_id,
        diff="--- a/app.py\n+++ b/app.py\n",
        description="Use a parameterized query.",
        provenance=Provenance(producer="repair"),
    )


_VULNERABLE_SOURCE = "import subprocess\n\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n"

_FIXING_DIFF = (
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,5 +1,5 @@\n"
    " import subprocess\n"
    " \n"
    " \n"
    " def run(cmd):\n"
    "-    subprocess.call(cmd, shell=True)\n"
    "+    subprocess.call(cmd, shell=False)\n"
)


def _bandit_finding() -> Finding:
    return Finding(
        rule_id="B602",
        title="bandit: B602",
        message="shell=True is dangerous",
        cwe=78,
        locations=(SourceLocation(path="app.py", start_line=5),),
        provenance=Provenance(producer="bandit"),
    )


def _fixing_patch(finding_id: str) -> Patch:
    return Patch(
        finding_id=finding_id,
        diff=_FIXING_DIFF,
        description="Disable shell=True.",
        files_changed=("app.py",),
        provenance=Provenance(producer="repair"),
    )


class TestReviewerAgent:
    def test_name_is_reviewer(self) -> None:
        assert ReviewerAgent(llm=_ScriptedLLM([])).name == "reviewer"

    def test_no_patches_produces_no_review_notes(self, tmp_path: Path) -> None:
        agent = ReviewerAgent(llm=_ScriptedLLM([]))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.notes_from("reviewer") == ()

    def test_approve_verdict_is_recorded_as_a_note(self, tmp_path: Path) -> None:
        finding = _finding()
        patch = _patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: APPROVE - the diff correctly parameterizes the query"])
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.notes_from("reviewer") == (
            f"{patch.id}: APPROVE - the diff correctly parameterizes the query",
        )

    def test_reject_and_needs_changes_verdicts_are_parsed(self, tmp_path: Path) -> None:
        finding_a, finding_b = _finding("A"), _finding("B")
        patch_a, patch_b = _patch(finding_a.id), _patch(finding_b.id)
        llm = _ScriptedLLM(
            ["REVIEW: REJECT - breaks existing behavior", "REVIEW: NEEDS_CHANGES - missing tests"]
        )
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding_a, finding_b))
            .with_patches((patch_a, patch_b))
        )
        result = agent.run(state)
        assert result.notes_from("reviewer") == (
            f"{patch_a.id}: REJECT - breaks existing behavior",
            f"{patch_b.id}: NEEDS_CHANGES - missing tests",
        )

    def test_unparseable_response_defaults_to_needs_changes(self, tmp_path: Path) -> None:
        finding = _finding()
        patch = _patch(finding.id)
        llm = _ScriptedLLM(["this diff looks okay I think"])
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.notes_from("reviewer")[0].startswith(f"{patch.id}: NEEDS_CHANGES")

    def test_none_response_text_defaults_to_needs_changes(self, tmp_path: Path) -> None:
        finding = _finding()
        patch = _patch(finding.id)
        agent = ReviewerAgent(llm=_ScriptedLLM([None]))
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.notes_from("reviewer")[0].startswith(f"{patch.id}: NEEDS_CHANGES")

    def test_never_sets_a_gate_field_on_the_patch(self, tmp_path: Path) -> None:
        finding = _finding()
        patch = _patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        reviewed_patch = result.patches[0]
        assert reviewed_patch.tests_pass is None
        assert reviewed_patch.rescan_clean is None
        assert reviewed_patch.exploit_neutralized is None
        assert reviewed_patch.is_validated is False

    def test_patch_referencing_a_missing_finding_still_gets_reviewed(self, tmp_path: Path) -> None:
        patch = _patch("no-such-finding-id")
        llm = _ScriptedLLM(["REVIEW: APPROVE - fine"])
        agent = ReviewerAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_patches((patch,))
        agent.run(state)
        prompt = llm.requests[0].messages[0].content
        assert "finding not found in this run" in prompt

    def test_renders_patch_description_and_diff_into_the_prompt(self, tmp_path: Path) -> None:
        finding = _finding()
        patch = _patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: APPROVE - fine"])
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        agent.run(state)
        prompt = llm.requests[0].messages[0].content
        assert patch.description in prompt
        assert "+++ b/app.py" in prompt

    def test_marks_itself_completed(self, tmp_path: Path) -> None:
        agent = ReviewerAgent(llm=_ScriptedLLM([]))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("reviewer",)

    def test_review_parsing_is_case_insensitive(self, tmp_path: Path) -> None:
        finding = _finding()
        patch = _patch(finding.id)
        llm = _ScriptedLLM(["review: approve - lowercase works too"])
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert "APPROVE" in result.notes_from("reviewer")[0]


class TestRescanGate:
    """`scanners` given -> genuine apply-and-rescan, using the real BanditScanner + git."""

    def test_a_fixing_patch_sets_rescan_clean_true(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        finding = _bandit_finding()
        patch = _fixing_patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm, scanners=(BanditScanner(),))
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.patches[0].rescan_clean is True

    def test_a_non_fixing_patch_sets_rescan_clean_false(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        finding = _bandit_finding()
        # A diff that applies but leaves the vulnerable call untouched.
        non_fixing_diff = (
            "--- a/app.py\n+++ b/app.py\n@@ -1,5 +1,5 @@\n import subprocess\n \n \n"
            "-def run(cmd):\n+def run(cmd):  # noop\n     subprocess.call(cmd, shell=True)\n"
        )
        patch = Patch(
            finding_id=finding.id,
            diff=non_fixing_diff,
            description="noop",
            files_changed=("app.py",),
            provenance=Provenance(producer="repair"),
        )
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm, scanners=(BanditScanner(),))
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.patches[0].rescan_clean is False

    def test_an_unapplyable_patch_leaves_rescan_clean_none(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        finding = _bandit_finding()
        patch = Patch(
            finding_id=finding.id,
            diff="--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-nonsense context\n+fixed\n",
            description="bad diff",
            files_changed=("app.py",),
            provenance=Provenance(producer="repair"),
        )
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm, scanners=(BanditScanner(),))
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.patches[0].rescan_clean is None

    def test_no_scanners_given_leaves_rescan_clean_none(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        finding = _bandit_finding()
        patch = _fixing_patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.patches[0].rescan_clean is None

    def test_missing_finding_leaves_rescan_clean_none(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        patch = _fixing_patch("no-such-finding-id")
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm, scanners=(BanditScanner(),))
        request = AnalysisRequest(root=tmp_path, languages=("python",))
        state = RunState(request=request).with_patches((patch,))
        result = agent.run(state)
        assert result.patches[0].rescan_clean is None

    def test_patches_are_updated_not_appended(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        finding = _bandit_finding()
        patch = _fixing_patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: APPROVE - looks correct"])
        agent = ReviewerAgent(llm=llm, scanners=(BanditScanner(),))
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert len(result.patches) == 1
        assert result.patches[0].id == patch.id

    def test_gate_result_does_not_affect_the_advisory_llm_note(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        finding = _bandit_finding()
        patch = _fixing_patch(finding.id)
        llm = _ScriptedLLM(["REVIEW: NEEDS_CHANGES - style nit"])
        agent = ReviewerAgent(llm=llm, scanners=(BanditScanner(),))
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        assert result.patches[0].rescan_clean is True
        assert result.notes_from("reviewer")[0].startswith(f"{patch.id}: NEEDS_CHANGES")


_POC_MARKER = "CORTEXWARD_POC_reviewer"


class _DictStore:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_artifact(self, content: bytes) -> str:
        ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
        self.store[ref] = content
        return ref

    def get_artifact(self, ref: str) -> bytes:
        return self.store[ref]


class _FakeSandbox:
    """Returns a pytest result for a pytest command, else a PoC result."""

    isolation_tier = "fake"

    def __init__(self, *, pytest_exit: int = 0, poc_stdout: str = "") -> None:
        self._pytest_exit = pytest_exit
        self._poc_stdout = poc_stdout
        self.specs: list[ExecutionSpec] = []

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self.specs.append(spec)
        if "pytest" in spec.command:
            return ExecutionResult(
                exit_code=self._pytest_exit,
                stdout="",
                stderr="",
                timed_out=False,
                duration_seconds=0.1,
            )
        return ExecutionResult(
            exit_code=0, stdout=self._poc_stdout, stderr="", timed_out=False, duration_seconds=0.1
        )


def _bandit_finding_with_poc(store: _DictStore) -> Finding:
    poc_ref = store.put_artifact(b"import importlib.util  # scripted poc\n")
    return Finding(
        rule_id="B602",
        title="bandit: B602",
        message="shell=True is dangerous",
        cwe=78,
        locations=(SourceLocation(path="app.py", start_line=5),),
        evidence=(
            Evidence(
                kind=EvidenceKind.EXPLOIT_POC,
                rung=VerificationRung.DYNAMIC_POC,
                supports=True,
                summary="poc fired",
                provenance=Provenance(producer="poc"),
                artifact_ref=poc_ref,
                data={"poc_marker": _POC_MARKER, "poc_path": "app.py"},
            ),
        ),
        provenance=Provenance(producer="bandit"),
    )


class TestSandboxGates:
    """`sandbox`+`artifacts` given -> Gate B (tests) and Gate D (PoC) also run."""

    def test_all_gates_passing_validates_the_patch(self, tmp_path: Path) -> None:
        # The full loop: real Bandit rescan (Gate C) on a fixing patch, plus a
        # sandbox where the tests pass (Gate B) and the PoC no longer triggers
        # (Gate D) -> every gate green -> Patch.is_validated is True.
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _bandit_finding_with_poc(store)
        patch = _fixing_patch(finding.id)
        sandbox = _FakeSandbox(pytest_exit=0, poc_stdout="no marker: neutralized")
        agent = ReviewerAgent(
            llm=_ScriptedLLM(["REVIEW: APPROVE - fixed"]),
            scanners=(BanditScanner(),),
            sandbox=sandbox,
            artifacts=store,
        )
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        gated = result.patches[0]
        assert gated.rescan_clean is True
        assert gated.tests_pass is True
        assert gated.exploit_neutralized is True
        assert gated.is_validated is True

    def test_failing_tests_and_still_exploitable_are_recorded(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _bandit_finding_with_poc(store)
        patch = _fixing_patch(finding.id)
        # Tests fail (exit 1); the PoC still triggers (marker present).
        sandbox = _FakeSandbox(pytest_exit=1, poc_stdout=f"pwned {_POC_MARKER}")
        agent = ReviewerAgent(
            llm=_ScriptedLLM(["REVIEW: REJECT - broken"]),
            scanners=(BanditScanner(),),
            sandbox=sandbox,
            artifacts=store,
        )
        state = (
            RunState(request=AnalysisRequest(root=tmp_path, languages=("python",)))
            .with_findings((finding,))
            .with_patches((patch,))
        )
        result = agent.run(state)
        gated = result.patches[0]
        assert gated.tests_pass is False
        assert gated.exploit_neutralized is False
        assert gated.is_validated is False

    def test_inconclusive_sandbox_gates_leave_fields_unset(self, tmp_path: Path) -> None:
        # A patch that doesn't apply makes both sandbox gates inconclusive, so
        # neither tests_pass nor exploit_neutralized is set.
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _bandit_finding_with_poc(store)
        bad_patch = Patch(
            finding_id=finding.id,
            diff="--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-nope\n+fixed\n",
            description="bad diff",
            files_changed=("app.py",),
            provenance=Provenance(producer="repair"),
        )
        sandbox = _FakeSandbox(pytest_exit=0, poc_stdout="")
        agent = ReviewerAgent(
            llm=_ScriptedLLM(["REVIEW: NEEDS_CHANGES - won't apply"]),
            sandbox=sandbox,
            artifacts=store,
        )
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings((finding,))
            .with_patches((bad_patch,))
        )
        result = agent.run(state)
        gated = result.patches[0]
        assert gated.tests_pass is None
        assert gated.exploit_neutralized is None
        assert sandbox.specs == []  # neither gate reached the sandbox

    def test_sandbox_without_a_finding_runs_gate_b_only(self, tmp_path: Path) -> None:
        # A patch whose finding isn't in this run: Gate B (no finding needed)
        # runs; Gate D (needs the finding's PoC) is skipped.
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        patch = _fixing_patch("no-such-finding-id")
        sandbox = _FakeSandbox(pytest_exit=0)
        agent = ReviewerAgent(
            llm=_ScriptedLLM(["REVIEW: APPROVE - fine"]),
            sandbox=sandbox,
            artifacts=store,
        )
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_patches((patch,))
        result = agent.run(state)
        gated = result.patches[0]
        assert gated.tests_pass is True
        assert gated.exploit_neutralized is None
