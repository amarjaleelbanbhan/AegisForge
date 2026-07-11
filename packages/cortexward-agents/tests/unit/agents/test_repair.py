"""Unit tests for `RepairAgent`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import RepairAgent, RunState
from cortexward.domain import Finding, FindingState, Patch, Provenance, SourceLocation
from cortexward.ports import AnalysisRequest, CompletionRequest, CompletionResult, TokenUsage

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


def _finding(rule_id: str = "R1", state: FindingState = FindingState.VERIFIED) -> Finding:
    finding = Finding(
        rule_id=rule_id,
        title="t",
        message="SQL built from string concatenation",
        cwe=89,
        locations=(SourceLocation(path="app.py", start_line=3),),
        provenance=Provenance(producer="test"),
    )
    return finding.with_state(state)


_GOOD_REPAIR = (
    "DESCRIPTION: Use a parameterized query instead of string concatenation.\n"
    "DIFF:\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -3,1 +3,1 @@\n"
    '-query = f"SELECT * FROM t WHERE id={user_id}"\n'
    '+query = "SELECT * FROM t WHERE id=%s"; params = (user_id,)\n'
)


class TestRepairAgent:
    def test_name_is_repair(self) -> None:
        assert RepairAgent(llm=_ScriptedLLM([])).name == "repair"

    def test_only_processes_verified_findings(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([_GOOD_REPAIR])
        agent = RepairAgent(llm=llm)
        verified = _finding("V", FindingState.VERIFIED)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (verified, _finding("C", FindingState.CANDIDATE))
        )
        result = agent.run(state)
        assert len(llm.requests) == 1
        assert len(result.patches) == 1
        assert result.patches[0].finding_id == verified.id

    def test_no_verified_findings_produces_no_patches(self, tmp_path: Path) -> None:
        agent = RepairAgent(llm=_ScriptedLLM([]))
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (_finding("C", FindingState.CANDIDATE),)
        )
        result = agent.run(state)
        assert result.patches == ()

    def test_produces_a_patch_with_description_and_diff(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([_GOOD_REPAIR])
        agent = RepairAgent(llm=llm)
        finding = _finding()
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        result = agent.run(state)
        patch = result.patches[0]
        assert patch.finding_id == finding.id
        assert patch.description == "Use a parameterized query instead of string concatenation."
        assert "SELECT * FROM t" in patch.diff
        assert patch.provenance.producer == "repair"
        assert patch.provenance.model == "fake-model"

    def test_files_changed_is_parsed_from_the_diff_header(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([_GOOD_REPAIR])
        agent = RepairAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.patches[0].files_changed == ("app.py",)

    def test_unparseable_response_produces_no_patch(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["I don't know how to fix this."])
        agent = RepairAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.patches == ()

    def test_none_response_text_produces_no_patch(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([None])
        agent = RepairAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.patches == ()

    def test_missing_description_marker_produces_no_patch(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["DIFF:\n--- a\n+++ b\n"])
        agent = RepairAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.patches == ()

    def test_empty_diff_after_marker_produces_no_patch(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["DESCRIPTION: fix it\nDIFF:\n   \n"])
        agent = RepairAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.patches == ()

    def test_note_reports_patch_and_skip_counts(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([_GOOD_REPAIR, "no diff here"])
        agent = RepairAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (_finding("A"), _finding("B"))
        )
        result = agent.run(state)
        assert result.notes_from("repair") == (
            "proposed 1 patch(es); 1 unparseable repair response(s)",
        )

    def test_marks_itself_completed(self, tmp_path: Path) -> None:
        agent = RepairAgent(llm=_ScriptedLLM([]))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("repair",)

    def test_patches_append_to_existing_patches(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([_GOOD_REPAIR])
        agent = RepairAgent(llm=llm)
        existing_patch = Patch(
            finding_id="prior",
            diff="--- a\n+++ b\n",
            description="d",
            provenance=Provenance(producer="x"),
        )
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_patches((existing_patch,))
            .with_findings((_finding(),))
        )
        result = agent.run(state)
        assert len(result.patches) == 2
        assert result.patches[0] is existing_patch
