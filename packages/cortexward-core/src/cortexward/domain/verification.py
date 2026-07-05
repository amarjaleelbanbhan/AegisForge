"""The Verification Ladder: turning evidence into calibrated conclusions.

This module is the formal core of CortexWard's central thesis. Given the
:class:`~cortexward.domain.models.Evidence` attached to a finding, it computes:

* the highest **rung** of the ladder reached by *independent* (non-LLM) evidence,
* a calibrated **confidence** that the finding is a real, exploitable issue,
* a standards-aligned **VEX status**, and
* a recommended lifecycle **state**.

Confidence is combined in log-odds space: each piece of evidence contributes a
signed weight, and the total is squashed through a logistic function. This gives
a principled, monotonic, and explainable score — adding supporting evidence can
only raise confidence, adding refuting evidence can only lower it.

Two safety policies are baked in, reflecting CortexWard's trust model:

1. **An LLM is never sufficient on its own.** Model judgements contribute a
   bounded amount of confidence and *cannot* advance a finding up the ladder;
   only concrete analysis (reachability, taint, PoC, differential test) can.
2. **Refutation is first-class.** Positive evidence that a finding is not
   exploitable drives it toward ``NOT_AFFECTED`` / ``REFUTED`` rather than merely
   being ignored.
"""

from __future__ import annotations

import math

from cortexward.domain.enums import (
    EvidenceKind,
    FindingState,
    VerificationRung,
    VexStatus,
)
from cortexward.domain.models import Evidence, Finding
from cortexward.domain.value_objects import Assessment

# --- Calibration constants -------------------------------------------------
#
# Weights are expressed in log-odds. A prior below zero means "assume not a real
# issue until corroborated", so a lone pattern match sits barely above a coin
# flip while concrete dynamic evidence dominates.

_PRIOR_LOG_ODDS = -0.4

_SUPPORT_WEIGHTS: dict[EvidenceKind, float] = {
    EvidenceKind.STATIC_MATCH: 0.6,
    EvidenceKind.LLM_ASSESSMENT: 0.5,
    EvidenceKind.REACHABILITY_PROOF: 1.0,
    EvidenceKind.TAINT_TRACE: 1.6,
    EvidenceKind.EXPLOIT_POC: 3.0,
    EvidenceKind.DIFFERENTIAL_TEST: 3.5,
    EvidenceKind.HUMAN_TRIAGE: 4.0,
    EvidenceKind.REFUTATION: 0.0,  # only meaningful as refuting evidence
}

_REFUTE_WEIGHTS: dict[EvidenceKind, float] = {
    EvidenceKind.REFUTATION: 3.0,
    EvidenceKind.REACHABILITY_PROOF: 2.5,  # proven unreachable
    EvidenceKind.TAINT_TRACE: 1.5,  # no taint path found
    EvidenceKind.HUMAN_TRIAGE: 4.0,
    EvidenceKind.DIFFERENTIAL_TEST: 3.0,  # test fails to reproduce
    EvidenceKind.EXPLOIT_POC: 2.0,  # PoC could not succeed
    EvidenceKind.LLM_ASSESSMENT: 0.5,
    EvidenceKind.STATIC_MATCH: 0.3,
}

# Confidence ceiling when the *only* supporting evidence is model judgement.
_LLM_ONLY_CONFIDENCE_CAP = 0.65

# Decision thresholds on the calibrated confidence.
VERIFIED_THRESHOLD = 0.80
TRIAGE_THRESHOLD = 0.55
REFUTED_THRESHOLD = 0.15
AFFECTED_THRESHOLD = 0.80

# States that assessment must never silently overwrite.
_TERMINAL_STATES = frozenset({FindingState.PATCHED, FindingState.DISMISSED})


def _sigmoid(x: float) -> float:
    # Numerically stable logistic function.
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _weight_for(ev: Evidence) -> float:
    """Signed log-odds contribution of one piece of evidence."""
    if ev.weight is not None:
        magnitude = abs(ev.weight)
    elif ev.supports:
        magnitude = _SUPPORT_WEIGHTS.get(ev.kind, 0.5)
    else:
        magnitude = _REFUTE_WEIGHTS.get(ev.kind, 0.5)
    return magnitude if ev.supports else -magnitude


def _highest_independent_rung(evidence: tuple[Evidence, ...]) -> VerificationRung:
    """Highest ladder rung reached by non-LLM *supporting* evidence.

    LLM assessments are intentionally excluded: a model cannot, by itself, move
    a finding up the ladder. This enforces the "never rely solely on an LLM"
    policy structurally rather than by convention.
    """
    rungs = [ev.rung for ev in evidence if ev.supports and ev.kind != EvidenceKind.LLM_ASSESSMENT]
    return max(rungs, default=VerificationRung.NONE)


def calibrate_confidence(evidence: tuple[Evidence, ...]) -> float:
    """Combine evidence into a calibrated confidence in ``[0, 1]``."""
    log_odds = _PRIOR_LOG_ODDS + sum(_weight_for(ev) for ev in evidence)
    confidence = _sigmoid(log_odds)

    has_independent_support = any(
        ev.supports and ev.kind != EvidenceKind.LLM_ASSESSMENT for ev in evidence
    )
    if not has_independent_support:
        confidence = min(confidence, _LLM_ONLY_CONFIDENCE_CAP)
    return confidence


def _vex_for(state: FindingState, confidence: float, rung: VerificationRung) -> VexStatus:
    if state == FindingState.PATCHED:
        return VexStatus.FIXED
    if state == FindingState.REFUTED or confidence <= REFUTED_THRESHOLD:
        return VexStatus.NOT_AFFECTED
    if rung >= VerificationRung.DYNAMIC_POC and confidence >= AFFECTED_THRESHOLD:
        return VexStatus.AFFECTED
    return VexStatus.UNDER_INVESTIGATION


def _recommended_state(
    current: FindingState,
    confidence: float,
    rung: VerificationRung,
) -> FindingState:
    if current in _TERMINAL_STATES:
        return current
    if confidence <= REFUTED_THRESHOLD:
        return FindingState.REFUTED
    independent_and_deep = rung >= VerificationRung.TAINT_CONFIRMED
    if independent_and_deep and confidence >= VERIFIED_THRESHOLD:
        return FindingState.VERIFIED
    if confidence >= TRIAGE_THRESHOLD:
        return FindingState.TRIAGED
    return FindingState.CANDIDATE


def assess(finding: Finding) -> Assessment:
    """Produce a full :class:`Assessment` for a finding from its evidence.

    Pure and deterministic: identical evidence always yields the identical
    assessment, which is what makes runs reproducible and research-gradeable.
    """
    evidence = finding.evidence
    confidence = calibrate_confidence(evidence)
    rung = _highest_independent_rung(evidence)
    has_independent = any(ev.supports and ev.kind != EvidenceKind.LLM_ASSESSMENT for ev in evidence)
    recommended = _recommended_state(finding.state, confidence, rung)
    vex = _vex_for(recommended, confidence, rung)

    rationale: list[str] = [
        f"{len(evidence)} evidence item(s); highest independent rung={rung.name}",
        f"calibrated confidence={confidence:.3f}",
    ]
    if not has_independent:
        rationale.append("LLM-only support: confidence capped, cannot be VERIFIED")

    return Assessment(
        confidence=confidence,
        highest_rung=rung,
        has_independent_corroboration=has_independent,
        vex_status=vex,
        recommended_state=recommended,
        rationale=tuple(rationale),
    )


def apply_assessment(finding: Finding) -> Finding:
    """Return the finding transitioned to its assessment's recommended state.

    Terminal states (``PATCHED``/``DISMISSED``) are preserved. This is the only
    sanctioned way for automated verification to move a finding's lifecycle.
    """
    recommended = assess(finding).recommended_state
    return finding.with_state(recommended)
