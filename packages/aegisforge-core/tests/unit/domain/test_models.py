"""Unit tests for the domain value objects and the Finding aggregate."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aegisforge.domain import (
    EvidenceKind,
    FindingState,
    Patch,
    Provenance,
    Severity,
    SourceLocation,
)
from tests.conftest import make_evidence, make_finding

pytestmark = pytest.mark.unit


class TestSeverity:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, Severity.INFO),
            (3.9, Severity.LOW),
            (4.0, Severity.MEDIUM),
            (6.9, Severity.MEDIUM),
            (7.0, Severity.HIGH),
            (8.9, Severity.HIGH),
            (9.0, Severity.CRITICAL),
            (10.0, Severity.CRITICAL),
        ],
    )
    def test_from_cvss(self, score: float, expected: Severity) -> None:
        assert Severity.from_cvss(score) is expected

    def test_from_cvss_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            Severity.from_cvss(11.0)

    def test_is_ordered(self) -> None:
        assert Severity.CRITICAL > Severity.HIGH > Severity.MEDIUM


class TestSourceLocation:
    def test_single_point_defaults(self) -> None:
        loc = SourceLocation(path="a.py", start_line=5)
        assert loc.start_col == 1
        assert str(loc) == "a.py:5:1"

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(ValidationError):
            SourceLocation(path="", start_line=1)

    def test_rejects_zero_line(self) -> None:
        with pytest.raises(ValidationError):
            SourceLocation(path="a.py", start_line=0)

    def test_rejects_inverted_line_span(self) -> None:
        with pytest.raises(ValidationError, match="end_line"):
            SourceLocation(path="a.py", start_line=10, end_line=5)

    def test_rejects_inverted_column_on_single_line(self) -> None:
        with pytest.raises(ValidationError, match="end_col"):
            SourceLocation(path="a.py", start_line=10, start_col=20, end_line=10, end_col=5)

    def test_is_frozen(self) -> None:
        loc = SourceLocation(path="a.py", start_line=1)
        with pytest.raises(ValidationError):
            loc.start_line = 2  # type: ignore[misc]


class TestFinding:
    def test_defaults(self) -> None:
        finding = make_finding()
        assert finding.state is FindingState.CANDIDATE
        assert finding.id.startswith("find_")
        assert finding.cwe == 89

    def test_with_evidence_is_immutable(self) -> None:
        finding = make_finding()
        updated = finding.with_evidence(make_evidence())
        assert len(finding.evidence) == 0
        assert len(updated.evidence) == 1
        assert updated.id == finding.id
        assert updated.updated_at >= finding.updated_at

    def test_with_evidence_noop_without_args(self) -> None:
        finding = make_finding()
        assert finding.with_evidence() is finding

    def test_with_state_transition(self) -> None:
        finding = make_finding()
        moved = finding.with_state(FindingState.VERIFIED)
        assert finding.state is FindingState.CANDIDATE
        assert moved.state is FindingState.VERIFIED

    def test_with_state_same_is_noop(self) -> None:
        finding = make_finding()
        assert finding.with_state(FindingState.CANDIDATE) is finding

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            make_finding().model_copy(update={"nonexistent": 1}).model_validate(
                {**make_finding().model_dump(), "nonexistent": 1}
            )


class TestPatch:
    def _patch(self, **kw: object) -> Patch:
        base: dict[str, object] = {
            "finding_id": "find_1",
            "diff": "--- a\n+++ b\n",
            "description": "fix",
            "provenance": Provenance(producer="repair"),
        }
        base.update(kw)
        return Patch(**base)  # type: ignore[arg-type]

    def test_unvalidated_by_default(self) -> None:
        assert self._patch().is_validated is False

    def test_validated_requires_all_gates(self) -> None:
        assert self._patch(tests_pass=True, rescan_clean=True).is_validated is False
        assert (
            self._patch(tests_pass=True, rescan_clean=True, exploit_neutralized=True).is_validated
            is True
        )


def test_evidence_direction_defaults_to_support() -> None:
    ev = make_evidence(EvidenceKind.STATIC_MATCH)
    assert ev.supports is True
    assert ev.id.startswith("ev_")
