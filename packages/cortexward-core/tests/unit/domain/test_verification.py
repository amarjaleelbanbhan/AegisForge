"""Unit and property tests for the Verification Ladder calibration engine."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingState,
    VerificationRung,
    VexStatus,
    apply_assessment,
    assess,
    calibrate_confidence,
)
from cortexward.domain.verification import REFUTED_THRESHOLD, VERIFIED_THRESHOLD

pytestmark = pytest.mark.unit

MakeEvidence = Callable[..., Evidence]
MakeFinding = Callable[..., Finding]


class TestAssessmentOutcomes:
    def test_no_evidence_is_low_confidence_candidate(self, make_finding: MakeFinding) -> None:
        result = assess(make_finding())
        assert result.confidence < 0.5
        assert result.recommended_state is FindingState.CANDIDATE
        assert result.vex_status is VexStatus.UNDER_INVESTIGATION

    def test_lone_static_match_stays_candidate(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(make_evidence(EvidenceKind.STATIC_MATCH))
        result = assess(finding)
        # A single pattern match is barely above a coin flip and must not, by
        # itself, escalate a finding.
        assert result.recommended_state is FindingState.CANDIDATE
        assert result.highest_rung is VerificationRung.NONE

    def test_taint_trace_reaches_verified(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.STATIC_MATCH),
            make_evidence(EvidenceKind.TAINT_TRACE, rung=VerificationRung.TAINT_CONFIRMED),
        )
        result = assess(finding)
        assert result.confidence >= VERIFIED_THRESHOLD
        assert result.recommended_state is FindingState.VERIFIED
        assert result.has_independent_corroboration is True

    def test_dynamic_poc_is_affected(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.EXPLOIT_POC, rung=VerificationRung.DYNAMIC_POC),
        )
        result = assess(finding)
        assert result.vex_status is VexStatus.AFFECTED
        assert result.recommended_state is FindingState.VERIFIED

    def test_refutation_drives_not_affected(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.STATIC_MATCH),
            make_evidence(EvidenceKind.REFUTATION, supports=False),
        )
        result = assess(finding)
        assert result.confidence <= REFUTED_THRESHOLD
        assert result.recommended_state is FindingState.REFUTED
        assert result.vex_status is VexStatus.NOT_AFFECTED


class TestLlmPolicy:
    def test_llm_alone_cannot_verify(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        # Even an overwhelmingly confident model assertion may not climb the
        # ladder or be marked VERIFIED without independent corroboration.
        finding = make_finding(
            make_evidence(EvidenceKind.LLM_ASSESSMENT, weight=5.0),
        )
        result = assess(finding)
        assert result.has_independent_corroboration is False
        assert result.highest_rung is VerificationRung.NONE
        assert result.recommended_state is not FindingState.VERIFIED
        assert result.confidence <= 0.65

    def test_llm_rung_is_ignored_for_ladder(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        # An LLM claiming a high rung must not count toward the independent rung.
        finding = make_finding(
            make_evidence(EvidenceKind.LLM_ASSESSMENT, rung=VerificationRung.DYNAMIC_POC),
        )
        assert assess(finding).highest_rung is VerificationRung.NONE


class TestTerminalStates:
    def test_patched_maps_to_fixed_and_is_preserved(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.EXPLOIT_POC, rung=VerificationRung.DYNAMIC_POC),
        ).with_state(FindingState.PATCHED)
        result = assess(finding)
        assert result.recommended_state is FindingState.PATCHED
        assert result.vex_status is VexStatus.FIXED

    def test_dismissed_is_preserved(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.EXPLOIT_POC, rung=VerificationRung.DYNAMIC_POC),
        ).with_state(FindingState.DISMISSED)
        assert assess(finding).recommended_state is FindingState.DISMISSED


class TestApplyAssessment:
    def test_apply_transitions_state(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        finding = make_finding(
            make_evidence(EvidenceKind.STATIC_MATCH),
            make_evidence(EvidenceKind.TAINT_TRACE, rung=VerificationRung.TAINT_CONFIRMED),
        )
        assert finding.state is FindingState.CANDIDATE
        assert apply_assessment(finding).state is FindingState.VERIFIED

    def test_lone_taint_trace_is_triaged_not_verified(
        self, make_finding: MakeFinding, make_evidence: MakeEvidence
    ) -> None:
        # A single taint trace with no corroborating detection lands just below
        # the verified threshold — a deliberate, conservative calibration.
        finding = make_finding(
            make_evidence(EvidenceKind.TAINT_TRACE, rung=VerificationRung.TAINT_CONFIRMED),
        )
        assert apply_assessment(finding).state is FindingState.TRIAGED


# --- Property-based invariants ---------------------------------------------

_SUPPORTING_KINDS = st.sampled_from(
    [
        EvidenceKind.STATIC_MATCH,
        EvidenceKind.REACHABILITY_PROOF,
        EvidenceKind.TAINT_TRACE,
        EvidenceKind.EXPLOIT_POC,
        EvidenceKind.LLM_ASSESSMENT,
    ]
)


# make_evidence is a pure, stateless factory (each call returns a fresh,
# independent Evidence with no shared state), so reusing the same fixture
# instance across generated examples is safe; the health check exists for
# fixtures with state or side effects, which this is not.
_SUPPRESS_FIXTURE_HEALTH_CHECK = settings(
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@_SUPPRESS_FIXTURE_HEALTH_CHECK
@given(
    base=st.lists(_SUPPORTING_KINDS, max_size=6),
    extra=_SUPPORTING_KINDS,
)
def test_supporting_evidence_is_monotonic(
    base: list[EvidenceKind], extra: EvidenceKind, make_evidence: MakeEvidence
) -> None:
    """Adding supporting evidence never lowers calibrated confidence."""
    base_ev = tuple(make_evidence(k) for k in base)
    with_extra = (*base_ev, make_evidence(extra))
    assert calibrate_confidence(with_extra) >= calibrate_confidence(base_ev) - 1e-12


@_SUPPRESS_FIXTURE_HEALTH_CHECK
@given(kinds=st.lists(_SUPPORTING_KINDS, max_size=8))
def test_confidence_is_bounded(kinds: list[EvidenceKind], make_evidence: MakeEvidence) -> None:
    """Confidence always lands in the unit interval."""
    conf = calibrate_confidence(tuple(make_evidence(k) for k in kinds))
    assert 0.0 <= conf <= 1.0
