"""Core domain enumerations for CortexWard.

These types are deliberately free of I/O and framework coupling. They encode the
vocabulary the whole system reasons in: how severe a finding is, how thoroughly
it has been verified, where it sits in its lifecycle, and how we report it to the
outside world in standards-aligned form (SARIF / VEX).
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Severity(IntEnum):
    """Impact severity, ordered so comparisons are meaningful.

    The numeric ordering lets callers write ``severity >= Severity.HIGH`` and
    lets us map from/to CVSS bands without a lookup table at call sites.
    """

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_cvss(cls, score: float) -> Severity:
        """Map a CVSS v3.x base score (0.0 to 10.0) to a severity band.

        Bands follow the official CVSS v3.1 qualitative severity rating scale.
        """
        if not _CVSS_MIN <= score <= _CVSS_MAX:
            raise ValueError(f"CVSS score out of range [0, 10]: {score}")
        # Ascending upper bounds; the first band the score falls under wins.
        for upper_exclusive, severity in _CVSS_BANDS:
            if score < upper_exclusive:
                return severity
        return cls.CRITICAL


_CVSS_MIN = 0.0
_CVSS_MAX = 10.0
# (exclusive-upper-bound, band) pairs per the CVSS v3.1 severity rating scale.
_CVSS_BANDS: tuple[tuple[float, Severity], ...] = (
    (0.1, Severity.INFO),
    (4.0, Severity.LOW),
    (7.0, Severity.MEDIUM),
    (9.0, Severity.HIGH),
)


class VerificationRung(IntEnum):
    """Rungs of the CortexWard Verification Ladder.

    The central thesis of CortexWard is that a finding is only as trustworthy as
    the *strongest feasible evidence* gathered for it. Rather than a binary
    "did an exploit run?", we track how far up this ladder a finding has climbed.
    Higher rungs subsume lower ones and warrant higher confidence.

    - ``NONE``: only a raw detection signal (e.g. a pattern match) exists.
    - ``STATIC_REACHABILITY``: the sink is reachable from an entry point.
    - ``TAINT_CONFIRMED``: attacker-controlled data provably flows to the sink.
    - ``DYNAMIC_POC``: a proof-of-concept exploit executed successfully in a
      sandbox.
    - ``DIFFERENTIAL_TEST``: a test distinguishes vulnerable from fixed behaviour
      (the strongest rung — it also validates patches by construction).
    """

    NONE = 0
    STATIC_REACHABILITY = 1
    TAINT_CONFIRMED = 2
    DYNAMIC_POC = 3
    DIFFERENTIAL_TEST = 4


class EvidenceKind(StrEnum):
    """The kind of evidence a producer contributed about a finding.

    Evidence may *support* (the vulnerability is real) or *refute* (it is not);
    that direction is carried on the evidence record itself, not here.
    """

    STATIC_MATCH = "static_match"
    """A SAST rule / pattern matched (Semgrep, Bandit, CodeQL, ...)."""

    REACHABILITY_PROOF = "reachability_proof"
    """Graph analysis showing the sink is (un)reachable from an entry point."""

    TAINT_TRACE = "taint_trace"
    """A data-flow path from an untrusted source to a dangerous sink."""

    EXPLOIT_POC = "exploit_poc"
    """A concrete proof-of-concept executed in the sandbox."""

    DIFFERENTIAL_TEST = "differential_test"
    """A test that behaves differently on vulnerable vs. fixed code."""

    LLM_ASSESSMENT = "llm_assessment"
    """A language-model judgement. Never sufficient on its own (see policy)."""

    REFUTATION = "refutation"
    """Positive evidence that the finding is not exploitable (e.g. dead code)."""

    HUMAN_TRIAGE = "human_triage"
    """An explicit decision by a human reviewer; overrides automated signals."""


class FindingState(StrEnum):
    """Lifecycle state of a finding.

    Transitions are governed by the verification assessment and by explicit
    human or patch actions; see :mod:`cortexward.domain.verification`.
    """

    CANDIDATE = "candidate"
    """Newly detected; not yet corroborated."""

    TRIAGED = "triaged"
    """Assessed and deemed worth pursuing, but not yet strongly verified."""

    VERIFIED = "verified"
    """Corroborated by non-LLM evidence to at least the taint rung."""

    REFUTED = "refuted"
    """Positively shown not to be exploitable; a de-escalated false positive."""

    PATCHED = "patched"
    """A validated fix has been produced and the exploit no longer succeeds."""

    DISMISSED = "dismissed"
    """Closed by a human as not actionable (accepted risk, duplicate, etc.)."""


class VexStatus(StrEnum):
    """VEX (Vulnerability Exploitability eXchange) statuses.

    Aligned with the CycloneDX / CSAF VEX vocabularies. Emitting these is a
    first-class CortexWard output: it answers "is this actually exploitable in
    context?", which is exactly the question the Verification Ladder resolves.
    """

    NOT_AFFECTED = "not_affected"
    AFFECTED = "affected"
    FIXED = "fixed"
    UNDER_INVESTIGATION = "under_investigation"
