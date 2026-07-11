"""Unit tests for `CoordinatorAgent`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import CoordinatorAgent, RunState
from cortexward.domain import Finding, FindingState, Patch, Provenance, SourceLocation
from cortexward.ports import AnalysisRequest, CompletionRequest, CompletionResult, TokenUsage

pytestmark = pytest.mark.unit


class _ScriptedLLM:
    def __init__(self, text: str | None) -> None:
        self.model_id = "fake-model"
        self._text = text
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(
            text=self._text,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            model=self.model_id,
            stop_reason="end_turn",
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def cost_estimate(self, usage: TokenUsage) -> float:
        return 0.0


def _finding(rule_id: str, state: FindingState) -> Finding:
    finding = Finding(
        rule_id=rule_id,
        title="t",
        message="m",
        locations=(SourceLocation(path="app.py", start_line=1),),
        provenance=Provenance(producer="test"),
    )
    return finding.with_state(state)


def _patch(finding_id: str) -> Patch:
    return Patch(
        finding_id=finding_id,
        diff="--- a\n+++ b\n",
        description="d",
        provenance=Provenance(producer="x"),
    )


class TestCoordinatorAgent:
    def test_name_is_coordinator(self) -> None:
        assert CoordinatorAgent(llm=_ScriptedLLM("summary")).name == "coordinator"

    def test_renders_counts_into_the_prompt(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM("summary text")
        agent = CoordinatorAgent(llm=llm)
        state = (
            RunState(request=AnalysisRequest(root=tmp_path))
            .with_findings(
                (
                    _finding("A", FindingState.VERIFIED),
                    _finding("B", FindingState.VERIFIED),
                    _finding("C", FindingState.REFUTED),
                    _finding("D", FindingState.CANDIDATE),
                )
            )
            .with_patches((_patch("A"),))
        )
        agent.run(state)
        prompt = llm.requests[0].messages[0].content
        assert "Findings detected: 4" in prompt
        assert "Findings verified as real: 2" in prompt
        assert "Findings flagged as likely false positives: 1" in prompt
        assert "Patches proposed: 1" in prompt

    def test_records_the_model_summary_as_a_note(self, tmp_path: Path) -> None:
        agent = CoordinatorAgent(llm=_ScriptedLLM("2 verified, 1 patch proposed."))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.notes_from("coordinator") == ("2 verified, 1 patch proposed.",)

    def test_empty_model_text_falls_back_to_a_placeholder_note(self, tmp_path: Path) -> None:
        agent = CoordinatorAgent(llm=_ScriptedLLM(None))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.notes_from("coordinator") == ("(coordinator produced no summary text)",)

    def test_marks_itself_completed_and_increments_rounds(self, tmp_path: Path) -> None:
        agent = CoordinatorAgent(llm=_ScriptedLLM("summary"))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("coordinator",)
        assert state.rounds_completed == 1

    def test_zero_findings_and_patches_render_as_zero(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM("nothing found")
        agent = CoordinatorAgent(llm=llm)
        agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        prompt = llm.requests[0].messages[0].content
        assert "Findings detected: 0" in prompt
        assert "Patches proposed: 0" in prompt
