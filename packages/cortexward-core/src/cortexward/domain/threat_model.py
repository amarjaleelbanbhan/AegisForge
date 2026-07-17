"""STRIDE threat modeling grounded on scanner findings (MPS Phase 5).

A :class:`Threat` reclassifies an existing :class:`~cortexward.domain.models.
Finding` under Microsoft's STRIDE taxonomy (Spoofing, Tampering, Repudiation,
Information Disclosure, Denial of Service, Elevation of Privilege) — it does
not detect anything new. STRIDE and CWE are orthogonal classification
schemes with no canonical published mapping between them; :data:`_STRIDE_BY_CWE`
below is this project's own considered judgement, covering the CWEs its own
scanners (Bandit, detect-secrets) can actually produce plus a handful of CWEs
common in real-world CVEs an OSV-sourced finding could carry. A CWE absent
from the table yields an empty ``frozenset`` — deliberately, not a guess:
this mirrors `StaticGlobalKnowledge.cwe_summary()`'s "no entry means no
claim" convention (`cortexward.agents.memory`) rather than forcing every
finding into a category with no confident basis.

Whether a threat's location is reachable from a known entry point (the
"attack surface" / trust-boundary-crossing question) needs a `CodeGraph`
query, which this module — kept dependency-free like the rest of
`cortexward.domain` — cannot perform. `Threat.reachable_from_entrypoint` is
therefore populated by a CPG-aware analysis in `cortexward.agents.
threat_model`, not here; these are pure value objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from cortexward.domain.enums import Severity
from cortexward.domain.models import SourceLocation


class StrideCategory(StrEnum):
    """One of Microsoft's six STRIDE threat categories."""

    SPOOFING = "spoofing"
    TAMPERING = "tampering"
    REPUDIATION = "repudiation"
    INFORMATION_DISCLOSURE = "information_disclosure"
    DENIAL_OF_SERVICE = "denial_of_service"
    ELEVATION_OF_PRIVILEGE = "elevation_of_privilege"


_S = StrideCategory.SPOOFING
_T = StrideCategory.TAMPERING
_R = StrideCategory.REPUDIATION
_I = StrideCategory.INFORMATION_DISCLOSURE
_D = StrideCategory.DENIAL_OF_SERVICE
_E = StrideCategory.ELEVATION_OF_PRIVILEGE

_STRIDE_BY_CWE: dict[int, frozenset[StrideCategory]] = {
    20: frozenset({_T}),  # Improper Input Validation
    22: frozenset({_T, _I}),  # Path Traversal
    78: frozenset({_T, _E}),  # OS Command Injection
    79: frozenset({_S, _T, _I}),  # Cross-Site Scripting
    80: frozenset({_S, _T, _I}),  # Basic XSS
    89: frozenset({_T, _I}),  # SQL Injection
    94: frozenset({_T, _E}),  # Code Injection
    155: frozenset({_T}),  # Improper Neutralization of Wildcards
    209: frozenset({_I}),  # Information Exposure Through an Error Message
    259: frozenset({_S}),  # Hard-coded Password
    269: frozenset({_E}),  # Improper Privilege Management
    284: frozenset({_E}),  # Improper Access Control
    295: frozenset({_S, _T}),  # Improper Certificate Validation
    306: frozenset({_S, _E}),  # Missing Authentication for Critical Function
    319: frozenset({_I}),  # Cleartext Transmission of Sensitive Information
    326: frozenset({_I}),  # Inadequate Encryption Strength
    327: frozenset({_I, _T}),  # Use of a Broken or Risky Cryptographic Algorithm
    330: frozenset({_S, _T}),  # Use of Insufficiently Random Values
    347: frozenset({_S, _T}),  # Improper Verification of Cryptographic Signature
    377: frozenset({_T, _I}),  # Insecure Temporary File
    400: frozenset({_D}),  # Uncontrolled Resource Consumption
    494: frozenset({_T}),  # Download of Code Without Integrity Check
    502: frozenset({_T, _E}),  # Deserialization of Untrusted Data
    611: frozenset({_I, _D}),  # XML External Entities
    732: frozenset({_E, _I}),  # Incorrect Permission Assignment
    798: frozenset({_S}),  # Use of Hard-coded Credentials
    838: frozenset({_T}),  # Inappropriate Encoding for Output Context
    862: frozenset({_E}),  # Missing Authorization
    863: frozenset({_E}),  # Incorrect Authorization
    918: frozenset({_T, _I}),  # Server-Side Request Forgery
}


def stride_categories_for(cwe: int | None) -> frozenset[StrideCategory]:
    """The STRIDE categories a finding's CWE maps to, or an empty set if unknown.

    An empty result means "this project has no confident STRIDE mapping for
    this CWE" — not "this CWE has no security relevance."
    """
    if cwe is None:
        return frozenset()
    return _STRIDE_BY_CWE.get(cwe, frozenset())


class Threat(BaseModel):
    """A `Finding` reclassified under STRIDE, with an attack-surface signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    cwe: int = Field(ge=1)
    categories: frozenset[StrideCategory] = Field(min_length=1)
    severity: Severity
    location: SourceLocation | None = None
    reachable_from_entrypoint: bool = False
    """True only on a genuine control-flow proof from a known entry point.

    False means "not proven reachable by this run's heuristics," never
    "proven unreachable" — the same one-directional convention
    `VerifierAgent`'s `REACHABILITY_PROOF` evidence uses.
    """


class ThreatModel(BaseModel):
    """A STRIDE-categorized view over one scan's findings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    threats: tuple[Threat, ...] = Field(default_factory=tuple)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def by_category(self, category: StrideCategory) -> tuple[Threat, ...]:
        """Every threat classified under `category`."""
        return tuple(threat for threat in self.threats if category in threat.categories)

    @property
    def exposed(self) -> tuple[Threat, ...]:
        """Every threat with a genuine reachability proof from an entry point."""
        return tuple(threat for threat in self.threats if threat.reachable_from_entrypoint)


__all__ = ["StrideCategory", "Threat", "ThreatModel", "stride_categories_for"]
