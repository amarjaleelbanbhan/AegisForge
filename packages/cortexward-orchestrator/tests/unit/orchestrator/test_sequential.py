"""Unit tests for `SequentialOrchestrator` and `default_scanners`.

Uses both fake scanners (deterministic, fast) and the real `BanditScanner`/
`SecretsScanner` against a fixture directory (a genuine end-to-end run, no
mocking) — consistent with this codebase's preference for real integration
tests wherever the target is actually available in-process.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from cortexward.domain import SourceLocation
from cortexward.orchestrator import SequentialOrchestrator, default_scanners
from cortexward.ports import AnalysisRequest, OrchestratorPort, RawFinding, ScannerPort
from cortexward.scanners import BanditScanner, SecretsScanner

pytestmark = pytest.mark.unit


class _FakeScanner:
    def __init__(self, name: str, findings: Sequence[RawFinding]) -> None:
        self.name = name
        self._findings = tuple(findings)
        self.scan_calls: list[tuple[Path, tuple[str, ...]]] = []

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        self.scan_calls.append((root, tuple(languages)))
        return self._findings


def _raw(rule_id: str = "R1", line: int = 1, cwe: int | None = 89) -> RawFinding:
    return RawFinding(
        rule_id=rule_id,
        message="a possible issue",
        location=SourceLocation(path="app.py", start_line=line),
        cwe=cwe,
    )


class TestProtocolConformance:
    def test_sequential_orchestrator_satisfies_the_port(self) -> None:
        assert isinstance(SequentialOrchestrator(scanners=()), OrchestratorPort)


class TestRun:
    def test_calls_every_configured_scanner_with_the_request(self, tmp_path: Path) -> None:
        scanner_a = _FakeScanner("a", [])
        scanner_b = _FakeScanner("b", [])
        orchestrator = SequentialOrchestrator(scanners=(scanner_a, scanner_b))
        request = AnalysisRequest(root=tmp_path, languages=("python",))
        orchestrator.run(request)
        assert scanner_a.scan_calls == [(tmp_path, ("python",))]
        assert scanner_b.scan_calls == [(tmp_path, ("python",))]

    def test_findings_from_every_scanner_are_present_in_the_result(self, tmp_path: Path) -> None:
        scanner_a = _FakeScanner("a", [_raw(rule_id="R1", cwe=89)])
        scanner_b = _FakeScanner("b", [_raw(rule_id="R2", cwe=79)])
        orchestrator = SequentialOrchestrator(scanners=(scanner_a, scanner_b))
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        rule_ids = {finding.rule_id for finding in result.findings}
        assert rule_ids == {"R1", "R2"}

    def test_findings_are_correlated_across_scanners(self, tmp_path: Path) -> None:
        scanner_a = _FakeScanner("a", [_raw(rule_id="R1", cwe=89, line=4)])
        scanner_b = _FakeScanner("b", [_raw(rule_id="R2", cwe=89, line=4)])
        orchestrator = SequentialOrchestrator(scanners=(scanner_a, scanner_b))
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        assert len(result.findings) == 1
        assert len(result.findings[0].evidence) == 2

    def test_run_id_is_populated_and_unique_per_call(self, tmp_path: Path) -> None:
        orchestrator = SequentialOrchestrator(scanners=())
        request = AnalysisRequest(root=tmp_path)
        first = orchestrator.run(request)
        second = orchestrator.run(request)
        assert first.run_id
        assert first.run_id != second.run_id

    def test_no_scanners_yields_no_findings(self, tmp_path: Path) -> None:
        result = SequentialOrchestrator(scanners=()).run(AnalysisRequest(root=tmp_path))
        assert result.findings == ()

    def test_patches_default_to_empty(self, tmp_path: Path) -> None:
        result = SequentialOrchestrator(scanners=()).run(AnalysisRequest(root=tmp_path))
        assert result.patches == ()


class TestRealScannersEndToEnd:
    def test_a_real_scan_finds_a_known_vulnerability_and_a_known_secret(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "vuln.py").write_text(
            "import subprocess\n"
            "def run(cmd):\n"
            "    subprocess.call(cmd, shell=True)\n"
            "github_token = 'ghp_' + '1234567890abcdefghijklmnopqrstuvwxyzAB'\n"
        )
        orchestrator = SequentialOrchestrator(scanners=(BanditScanner(), SecretsScanner()))
        result = orchestrator.run(AnalysisRequest(root=tmp_path))
        producers = {tag for finding in result.findings for tag in finding.tags}
        assert "bandit" in producers
        assert "detect-secrets" in producers


class TestDefaultScanners:
    def test_discovers_at_least_the_bundled_scanners(self) -> None:
        scanners = default_scanners()
        names = {scanner.name for scanner in scanners}
        assert {"bandit", "detect-secrets", "osv"} <= names

    def test_every_discovered_scanner_satisfies_the_port(self) -> None:
        for scanner in default_scanners():
            assert isinstance(scanner, ScannerPort)
