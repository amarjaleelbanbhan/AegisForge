"""Unit tests for `ScannerAgent`."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from cortexward.agents import RunState, ScannerAgent
from cortexward.domain import SourceLocation
from cortexward.ports import AnalysisRequest, RawFinding

pytestmark = pytest.mark.unit


class _FakeScanner:
    def __init__(self, name: str, findings: Sequence[RawFinding]) -> None:
        self.name = name
        self._findings = list(findings)
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        self.calls.append((root, tuple(languages)))
        return list(self._findings)


def _raw(
    rule_id: str = "R1", path: str = "app.py", line: int = 1, cwe: int | None = 89
) -> RawFinding:
    return RawFinding(
        rule_id=rule_id,
        message=f"{rule_id} triggered",
        location=SourceLocation(path=path, start_line=line),
        cwe=cwe,
    )


class TestScannerAgent:
    def test_name_is_scanner(self) -> None:
        assert ScannerAgent(scanners=()).name == "scanner"

    def test_runs_every_configured_scanner_with_the_request_root_and_languages(
        self, tmp_path: Path
    ) -> None:
        scanner_a = _FakeScanner("a", [_raw()])
        scanner_b = _FakeScanner("b", [])
        agent = ScannerAgent(scanners=(scanner_a, scanner_b))
        request = AnalysisRequest(root=tmp_path, languages=("python",))
        agent.run(RunState(request=request))
        assert scanner_a.calls == [(tmp_path, ("python",))]
        assert scanner_b.calls == [(tmp_path, ("python",))]

    def test_correlates_results_into_findings(self, tmp_path: Path) -> None:
        scanner = _FakeScanner("bandit", [_raw(rule_id="B602")])
        agent = ScannerAgent(scanners=(scanner,))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert len(state.findings) == 1
        assert state.findings[0].rule_id == "B602"

    def test_shared_cwe_and_location_across_scanners_gets_merged(self, tmp_path: Path) -> None:
        scanner_a = _FakeScanner("a", [_raw(rule_id="R1", path="app.py", line=5, cwe=89)])
        scanner_b = _FakeScanner("b", [_raw(rule_id="R2", path="app.py", line=5, cwe=89)])
        agent = ScannerAgent(scanners=(scanner_a, scanner_b))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert len(state.findings) == 1
        assert len(state.findings[0].evidence) == 2

    def test_no_scanners_produces_no_findings(self, tmp_path: Path) -> None:
        agent = ScannerAgent(scanners=())
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.findings == ()

    def test_note_reports_finding_and_scanner_counts(self, tmp_path: Path) -> None:
        scanner = _FakeScanner("bandit", [_raw()])
        agent = ScannerAgent(scanners=(scanner,))
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.notes_from("scanner") == (
            "1 finding(s) after correlation across 1 scanner(s)",
        )

    def test_marks_itself_completed(self, tmp_path: Path) -> None:
        agent = ScannerAgent(scanners=())
        state = agent.run(RunState(request=AnalysisRequest(root=tmp_path)))
        assert state.completed_agents == ("scanner",)
