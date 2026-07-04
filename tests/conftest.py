"""Shared test fixtures and builders for the AegisForge test suite."""

from __future__ import annotations

from aegisforge.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    Provenance,
    Severity,
    SourceLocation,
    VerificationRung,
)

_PROV = Provenance(producer="test", producer_version="0")


def make_evidence(
    kind: EvidenceKind = EvidenceKind.STATIC_MATCH,
    *,
    rung: VerificationRung = VerificationRung.NONE,
    supports: bool = True,
    weight: float | None = None,
    summary: str = "test evidence",
) -> Evidence:
    """Build an :class:`Evidence` value object with sensible defaults."""
    return Evidence(
        kind=kind,
        rung=rung,
        supports=supports,
        weight=weight,
        summary=summary,
        provenance=_PROV,
    )


def make_finding(*evidence: Evidence, cwe: int | None = 89) -> Finding:
    """Build a :class:`Finding` seeded with the given evidence."""
    return Finding(
        rule_id="test.rule",
        title="Test finding",
        message="A potential issue was detected.",
        severity=Severity.HIGH,
        cwe=cwe,
        locations=(SourceLocation(path="app/main.py", start_line=10),),
        evidence=tuple(evidence),
        provenance=_PROV,
    )
