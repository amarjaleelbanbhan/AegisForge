"""Derived, read-only value objects produced by domain services.

These are *conclusions* (as opposed to the *facts* in :mod:`models`): they are
computed from a finding's evidence and are never stored as ground truth.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from cortexward.domain.enums import FindingState, VerificationRung, VexStatus


class Assessment(BaseModel):
    """The outcome of running the Verification Ladder over a finding.

    Every field is derived from evidence by
    :func:`cortexward.domain.verification.assess`. The ``rationale`` explains the
    conclusion in human-readable form so findings remain auditable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: float = Field(ge=0.0, le=1.0)
    highest_rung: VerificationRung
    has_independent_corroboration: bool
    vex_status: VexStatus
    recommended_state: FindingState
    rationale: tuple[str, ...] = ()
