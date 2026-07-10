"""Unit tests for `RunState`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import RunState
from cortexward.domain import Finding, Patch, Provenance, SourceLocation
from cortexward.ports import AnalysisRequest

pytestmark = pytest.mark.unit


def _finding(rule_id: str = "R1") -> Finding:
    return Finding(
        rule_id=rule_id,
        title="t",
        message="m",
        locations=(SourceLocation(path="app.py", start_line=1),),
        provenance=Provenance(producer="test"),
    )


def _patch(finding_id: str = "find_1") -> Patch:
    return Patch(
        finding_id=finding_id,
        diff="--- a\n+++ b\n",
        description="fix",
        provenance=Provenance(producer="test"),
    )


def _state(root: Path) -> RunState:
    return RunState(request=AnalysisRequest(root=root))


class TestRunState:
    def test_default_fields_are_empty(self, tmp_path: Path) -> None:
        state = _state(tmp_path)
        assert state.findings == ()
        assert state.patches == ()
        assert state.notes == ()
        assert state.completed_agents == ()
        assert state.rounds_completed == 0

    def test_with_findings_replaces_not_appends(self, tmp_path: Path) -> None:
        state = _state(tmp_path).with_findings((_finding("A"),))
        state = state.with_findings((_finding("B"), _finding("C")))
        assert [f.rule_id for f in state.findings] == ["B", "C"]

    def test_with_patches_appends(self, tmp_path: Path) -> None:
        state = _state(tmp_path).with_patches((_patch("f1"),))
        state = state.with_patches((_patch("f2"),))
        assert [p.finding_id for p in state.patches] == ["f1", "f2"]

    def test_with_note_appends_and_is_attributed(self, tmp_path: Path) -> None:
        state = _state(tmp_path).with_note("planner", "note one")
        state = state.with_note("verifier", "note two")
        state = state.with_note("planner", "note three")
        assert state.notes == (
            ("planner", "note one"),
            ("verifier", "note two"),
            ("planner", "note three"),
        )

    def test_notes_from_filters_by_agent(self, tmp_path: Path) -> None:
        state = (
            _state(tmp_path)
            .with_note("planner", "a")
            .with_note("verifier", "b")
            .with_note("planner", "c")
        )
        assert state.notes_from("planner") == ("a", "c")
        assert state.notes_from("verifier") == ("b",)
        assert state.notes_from("repair") == ()

    def test_with_completed_appends(self, tmp_path: Path) -> None:
        state = _state(tmp_path).with_completed("planner").with_completed("scanner")
        assert state.completed_agents == ("planner", "scanner")

    def test_with_round_complete_increments(self, tmp_path: Path) -> None:
        state = _state(tmp_path)
        state = state.with_round_complete().with_round_complete()
        assert state.rounds_completed == 2

    def test_original_state_is_unmodified_by_with_methods(self, tmp_path: Path) -> None:
        original = _state(tmp_path)
        original.with_findings((_finding(),))
        original.with_note("x", "y")
        assert original.findings == ()
        assert original.notes == ()

    def test_is_frozen(self, tmp_path: Path) -> None:
        state = _state(tmp_path)
        with pytest.raises(AttributeError):
            state.rounds_completed = 5  # type: ignore[misc]
