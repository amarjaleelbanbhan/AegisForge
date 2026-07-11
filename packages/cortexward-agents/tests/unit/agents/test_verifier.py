"""Unit tests for `VerifierAgent`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import RunState, VerifierAgent
from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingState,
    Provenance,
    SourceLocation,
    VerificationRung,
)
from cortexward.ports import AnalysisRequest, CompletionRequest, CompletionResult, TokenUsage

pytestmark = pytest.mark.unit


class _ScriptedLLM:
    """Replays one text per `complete()` call, in order."""

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


def _finding(
    rule_id: str = "R1",
    cwe: int | None = 89,
    with_location: bool = True,
    with_static_evidence: bool = False,
) -> Finding:
    locations = (SourceLocation(path="app.py", start_line=3),) if with_location else ()
    evidence: tuple[Evidence, ...] = ()
    if with_static_evidence:
        evidence = (
            Evidence(
                kind=EvidenceKind.STATIC_MATCH,
                rung=VerificationRung.NONE,
                supports=True,
                summary="pattern match",
                provenance=Provenance(producer="bandit"),
            ),
        )
    return Finding(
        rule_id=rule_id,
        title="t",
        message="SQL built from string concatenation",
        cwe=cwe,
        locations=locations,
        evidence=evidence,
        provenance=Provenance(producer="test"),
    )


class TestVerifierAgent:
    def test_name_is_verifier(self) -> None:
        assert VerifierAgent(llm=_ScriptedLLM([])).name == "verifier"

    def test_renders_finding_fields_into_the_prompt(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: REAL - looks exploitable"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        agent.run(state)
        prompt = llm.requests[0].messages[0].content
        assert "R1" in prompt
        assert "89" in prompt
        assert "app.py:3:1" in prompt

    def test_missing_location_renders_as_unknown(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: UNCERTAIN - no context"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (_finding(with_location=False),)
        )
        agent.run(state)
        assert "unknown location" in llm.requests[0].messages[0].content

    def test_missing_cwe_renders_as_unknown(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: UNCERTAIN - no context"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (_finding(cwe=None),)
        )
        agent.run(state)
        assert "unknown" in llm.requests[0].messages[0].content

    def test_real_verdict_attaches_supporting_llm_assessment_evidence(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: REAL - matches known SQLi pattern"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        finding = result.findings[0]
        assert len(finding.evidence) == 1
        evidence = finding.evidence[0]
        assert evidence.kind == EvidenceKind.LLM_ASSESSMENT
        assert evidence.supports is True
        assert evidence.summary == "matches known SQLi pattern"
        assert evidence.provenance.producer == "verifier"
        assert evidence.provenance.model == "fake-model"

    def test_llm_evidence_alone_is_never_enough_to_change_state(self, tmp_path: Path) -> None:
        # No independent (non-LLM) evidence exists yet -- confidence is
        # capped below TRIAGE_THRESHOLD, so the domain's LLM-insufficiency
        # policy (cortexward.domain.verification) keeps the finding CANDIDATE
        # even for a "REAL" verdict.
        llm = _ScriptedLLM(["VERDICT: REAL - matches known SQLi pattern"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.findings[0].state == FindingState.CANDIDATE

    def test_real_verdict_combined_with_independent_evidence_reaches_triaged(
        self, tmp_path: Path
    ) -> None:
        # With independent STATIC_MATCH evidence already present (as Scanner
        # would attach), a REAL verdict's added confidence is enough to
        # cross TRIAGE_THRESHOLD -- but still nowhere near VERIFIED_THRESHOLD,
        # since that requires independent evidence at a real ladder rung.
        llm = _ScriptedLLM(["VERDICT: REAL - matches known SQLi pattern"])
        agent = VerifierAgent(llm=llm)
        finding = _finding(with_static_evidence=True)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((finding,))
        result = agent.run(state)
        assert result.findings[0].state == FindingState.TRIAGED

    def test_false_positive_verdict_attaches_refuting_evidence(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: FALSE_POSITIVE - input is a constant, not tainted"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        finding = result.findings[0]
        assert finding.evidence[0].supports is False
        assert finding.evidence[0].summary == "input is a constant, not tainted"

    def test_uncertain_verdict_leaves_the_finding_untouched(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: UNCERTAIN - not enough context to decide"])
        agent = VerifierAgent(llm=llm)
        original = _finding()
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((original,))
        result = agent.run(state)
        assert result.findings[0] == original

    def test_unparseable_response_is_treated_as_uncertain(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["I'm not sure about this one."])
        agent = VerifierAgent(llm=llm)
        original = _finding()
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((original,))
        result = agent.run(state)
        assert result.findings[0] == original

    def test_none_response_text_is_treated_as_uncertain(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM([None])
        agent = VerifierAgent(llm=llm)
        original = _finding()
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((original,))
        result = agent.run(state)
        assert result.findings[0] == original

    def test_processes_every_finding_in_state(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(
            ["VERDICT: REAL - a", "VERDICT: FALSE_POSITIVE - b", "VERDICT: UNCERTAIN - c"]
        )
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings(
            (_finding("R1"), _finding("R2"), _finding("R3"))
        )
        result = agent.run(state)
        assert len(result.findings) == 3
        assert len(llm.requests) == 3

    def test_note_reports_verified_count(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["VERDICT: UNCERTAIN - x"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.notes_from("verifier") == ("verified 1 finding(s)",)

    def test_marks_itself_completed(self, tmp_path: Path) -> None:
        agent = VerifierAgent(llm=_ScriptedLLM([]))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("verifier",)

    def test_verdict_parsing_is_case_insensitive(self, tmp_path: Path) -> None:
        llm = _ScriptedLLM(["verdict: real - lowercase works too"])
        agent = VerifierAgent(llm=llm)
        state = RunState(request=AnalysisRequest(root=tmp_path)).with_findings((_finding(),))
        result = agent.run(state)
        assert result.findings[0].evidence[0].supports is True
