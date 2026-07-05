"""Shared test fixtures and builders for the AegisForge test suite.

``make_evidence``/``make_finding`` are exposed as pytest fixtures (factory
functions) rather than plain importable helpers: with ``--import-mode=
importlib`` and no package ``__init__.py`` files under ``tests/`` (needed so
each workspace package's own ``tests/`` tree doesn't collide with its
siblings under the shared ``tests`` module name), pytest's fixture injection
is the portable way to share builders across test modules.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

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

MakeEvidence = Callable[..., Evidence]
MakeFinding = Callable[..., Finding]


@pytest.fixture
def make_evidence() -> MakeEvidence:
    """Factory fixture building an :class:`Evidence` with sensible defaults."""

    def _make_evidence(
        kind: EvidenceKind = EvidenceKind.STATIC_MATCH,
        *,
        rung: VerificationRung = VerificationRung.NONE,
        supports: bool = True,
        weight: float | None = None,
        summary: str = "test evidence",
    ) -> Evidence:
        return Evidence(
            kind=kind,
            rung=rung,
            supports=supports,
            weight=weight,
            summary=summary,
            provenance=_PROV,
        )

    return _make_evidence


@pytest.fixture
def make_finding() -> MakeFinding:
    """Factory fixture building a :class:`Finding` seeded with given evidence."""

    def _make_finding(*evidence: Evidence, cwe: int | None = 89) -> Finding:
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

    return _make_finding
