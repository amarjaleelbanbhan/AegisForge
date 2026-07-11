"""Unit tests for `PlannerAgent`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import PlannerAgent, RunState
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


class TestPlannerAgent:
    def test_name_is_planner(self) -> None:
        assert PlannerAgent(llm=_ScriptedLLM("plan")).name == "planner"

    def test_renders_root_and_languages_into_the_prompt(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM("Scan Python files with bandit and osv.")
        agent = PlannerAgent(llm=llm)
        request = AnalysisRequest(root=tmp_path, languages=("python",))
        agent.run(RunState(request=request))
        prompt = llm.requests[0].messages[0].content
        assert str(tmp_path) in prompt
        assert "python" in prompt

    def test_defaults_to_auto_detect_when_no_languages_given(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM("plan")
        agent = PlannerAgent(llm=llm)
        agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert "auto-detect" in llm.requests[0].messages[0].content

    def test_records_the_model_text_as_a_note(self, tmp_path: Path) -> None:
        agent = PlannerAgent(llm=_ScriptedLLM("Run bandit, osv, and detect-secrets."))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.notes_from("planner") == ("Run bandit, osv, and detect-secrets.",)

    def test_marks_itself_completed(self, tmp_path: Path) -> None:
        agent = PlannerAgent(llm=_ScriptedLLM("plan"))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("planner",)

    def test_empty_model_text_falls_back_to_a_placeholder_note(self, tmp_path: Path) -> None:
        agent = PlannerAgent(llm=_ScriptedLLM(None))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.notes_from("planner") == ("(planner produced no plan text)",)
