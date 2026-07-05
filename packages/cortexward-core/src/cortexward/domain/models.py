"""Core domain value objects and the Finding aggregate.

Design notes
------------
* Value objects (:class:`SourceLocation`, :class:`Provenance`, :class:`Evidence`,
  :class:`Patch`) are frozen and reject unknown fields. Findings flowing through
  the pipeline are adversarial input, so we validate strictly at every boundary.
* :class:`Finding` is the one mutable aggregate: its lifecycle *state* and its
  *evidence* accumulate as agents corroborate or refute it. All confidence and
  state logic lives in :mod:`cortexward.domain.verification` and operates on
  these structures without hidden coupling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cortexward.domain.enums import (
    EvidenceKind,
    FindingState,
    Severity,
    VerificationRung,
)


def _new_id(prefix: str) -> str:
    """Generate a short, prefixed, sortable-enough identifier."""
    return f"{prefix}_{uuid4().hex[:16]}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _Frozen(BaseModel):
    """Base for immutable, strictly-validated value objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceLocation(_Frozen):
    """A span of source code a finding refers to.

    Lines and columns are 1-indexed to match every editor and SARIF. A location
    may span multiple lines; ``end`` fields default to the start when a single
    point is meant.
    """

    path: str = Field(min_length=1, description="Repo-relative file path.")
    start_line: int = Field(ge=1)
    start_col: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_col: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_span(self) -> SourceLocation:
        end_line = self.end_line if self.end_line is not None else self.start_line
        if end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        single_line = end_line == self.start_line
        if single_line and self.end_col is not None and self.end_col < self.start_col:
            raise ValueError("end_col must be >= start_col on a single-line span")
        return self

    def __str__(self) -> str:
        return f"{self.path}:{self.start_line}:{self.start_col}"


class Provenance(_Frozen):
    """Where a piece of data came from — for reproducibility and audit.

    Every finding and every piece of evidence records provenance so any result
    can be traced back to the exact producer, version, model, and run that
    generated it. This underpins both research reproducibility and the trust
    story: nothing is asserted without an attributable source.
    """

    producer: str = Field(min_length=1, description="Tool or agent name, e.g. 'semgrep'.")
    producer_version: str | None = None
    model: str | None = Field(default=None, description="LLM id, if a model was involved.")
    run_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    extra: dict[str, str] = Field(default_factory=dict)


class Evidence(_Frozen):
    """A single corroborating or refuting signal about a finding.

    ``supports=True`` means "this makes the vulnerability more likely real";
    ``supports=False`` means "this argues it is not exploitable". The ``rung``
    records how high on the Verification Ladder this evidence reaches when it
    supports the finding (refuting evidence is scored separately).
    """

    id: str = Field(default_factory=lambda: _new_id("ev"))
    kind: EvidenceKind
    rung: VerificationRung = VerificationRung.NONE
    supports: bool = True
    summary: str = Field(min_length=1)
    provenance: Provenance
    weight: float | None = Field(
        default=None,
        description="Optional override of the default log-odds weight for this kind.",
    )
    artifact_ref: str | None = Field(
        default=None,
        description="Reference (path/URI/hash) to a stored artifact, e.g. a PoC script.",
    )
    data: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class Patch(_Frozen):
    """A proposed, minimal-diff fix for a finding.

    Patches are never auto-merged. They carry the unified diff plus enough
    metadata for the review gates (existing tests pass, scanners re-run clean,
    the original PoC no longer succeeds) to record their verdict.
    """

    id: str = Field(default_factory=lambda: _new_id("patch"))
    finding_id: str
    diff: str = Field(min_length=1, description="Unified diff of the fix.")
    description: str = Field(min_length=1)
    files_changed: tuple[str, ...] = ()
    provenance: Provenance
    tests_pass: bool | None = None
    rescan_clean: bool | None = None
    exploit_neutralized: bool | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def is_validated(self) -> bool:
        """True only when every safety gate has explicitly passed."""
        return bool(self.tests_pass and self.rescan_clean and self.exploit_neutralized)


class Finding(BaseModel):
    """The central aggregate: a potential security issue and its evidence.

    A finding starts life as a ``CANDIDATE`` from a single detector and gains
    trust as agents attach :class:`Evidence`. Its confidence, VEX status, and
    recommended lifecycle state are *derived* from that evidence by
    :mod:`cortexward.domain.verification`; this model stores the facts, not the
    conclusions.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = Field(default_factory=lambda: _new_id("find"))
    rule_id: str = Field(min_length=1, description="Detector rule identifier.")
    title: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Severity = Severity.MEDIUM
    cwe: int | None = Field(default=None, ge=1, description="Primary CWE id, e.g. 89 for SQLi.")
    locations: tuple[SourceLocation, ...] = Field(default_factory=tuple)
    evidence: tuple[Evidence, ...] = Field(default_factory=tuple)
    state: FindingState = FindingState.CANDIDATE
    provenance: Provenance
    tags: frozenset[str] = Field(default_factory=frozenset)
    related_ids: frozenset[str] = Field(default_factory=frozenset)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("cwe")
    @classmethod
    def _reject_zero_cwe(cls, value: int | None) -> int | None:
        return value

    def with_evidence(self, *evidence: Evidence) -> Finding:
        """Return a copy of this finding with additional evidence attached.

        Findings are updated functionally so callers never mutate shared state
        by accident; the orchestrator threads the new value through explicitly.
        """
        if not evidence:
            return self
        return self.model_copy(
            update={
                "evidence": self.evidence + tuple(evidence),
                "updated_at": _utcnow(),
            }
        )

    def with_state(self, state: FindingState) -> Finding:
        """Return a copy of this finding in a new lifecycle state."""
        if state == self.state:
            return self
        return self.model_copy(update={"state": state, "updated_at": _utcnow()})
