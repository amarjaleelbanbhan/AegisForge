"""Unit tests for `ReviewerAgent`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import ReviewerAgent, RunState
from cortexward.domain import Finding, Patch, Provenance, SourceLocation
from cortexward.ports import AnalysisRequest, CompletionRequest, CompletionResult, TokenUsage
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
