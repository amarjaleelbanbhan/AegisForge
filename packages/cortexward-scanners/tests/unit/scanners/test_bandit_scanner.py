"""Unit tests for the Bandit scanner adapter.

Runs the real `bandit` package against fixture files written to `tmp_path` —
no mocking of the subprocess or its JSON output, since the whole point of
this adapter is correctly invoking and parsing a real external tool.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cortexward.ports import ScannerPort
from cortexward.scanners import BanditScanner
from cortexward.scanners.bandit_scanner import _cwe_for, _location_for, _raw_fields

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestProtocolConformance:
    def test_bandit_scanner_satisfies_the_port(self) -> None:
        assert isinstance(BanditScanner(), ScannerPort)

    def test_name_is_bandit(self) -> None:
        assert BanditScanner().name == "bandit"


class TestScanning:
    def test_finds_a_known_vulnerability(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "vuln.py",
            "import subprocess\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n",
        )
        findings = list(BanditScanner().scan(tmp_path))
        shell_true = [f for f in findings if f.rule_id == "B602"]
        assert len(shell_true) == 1
        finding = shell_true[0]
        assert finding.location.start_line == 4
        assert finding.severity_hint == "HIGH"
        assert finding.cwe == 78
        assert "shell=True" in finding.message

    def test_clean_code_yields_no_findings(self, tmp_path: Path) -> None:
        _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
        findings = list(BanditScanner().scan(tmp_path))
        assert findings == []

    def test_finding_location_path_is_relative_to_root(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        _write(tmp_path / "pkg", "vuln.py", "password = 'hunter2'\n")
        findings = list(BanditScanner().scan(tmp_path))
        assert findings
        for finding in findings:
            assert not Path(finding.location.path).is_absolute()
            assert Path(finding.location.path).as_posix() == "pkg/vuln.py"

    def test_raw_preserves_bandit_native_fields(self, tmp_path: Path) -> None:
        _write(tmp_path, "vuln.py", "eval('1 + 1')\n")
        findings = list(BanditScanner().scan(tmp_path))
        assert findings
        assert "test_name" in findings[0].raw
        assert "issue_confidence" in findings[0].raw

    def test_excluded_directories_are_not_scanned(self, tmp_path: Path) -> None:
        vendored = tmp_path / ".venv" / "site-packages"
        vendored.mkdir(parents=True)
        _write(vendored, "vuln.py", "password = 'hunter2'\n")
        _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
        findings = list(BanditScanner().scan(tmp_path))
        assert findings == []

    def test_languages_filter_excludes_non_python_scans(self, tmp_path: Path) -> None:
        _write(tmp_path, "vuln.py", "password = 'hunter2'\n")
        findings = list(BanditScanner().scan(tmp_path, languages=("javascript",)))
        assert findings == []

    def test_languages_filter_including_python_still_scans(self, tmp_path: Path) -> None:
        _write(tmp_path, "vuln.py", "password = 'hunter2'\n")
        findings = list(BanditScanner().scan(tmp_path, languages=("python", "javascript")))
        assert findings != []

    def test_empty_directory_yields_no_findings(self, tmp_path: Path) -> None:
        findings = list(BanditScanner().scan(tmp_path))
        assert findings == []

    def test_empty_subprocess_stdout_yields_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A defensive guard, not a real Bandit behavior (Bandit always
        # prints a JSON skeleton even for an empty/missing target) — covers
        # the case where the underlying tool produces no output at all.
        def _empty_result(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _empty_result)
        findings = list(BanditScanner().scan(tmp_path))
        assert findings == []


class TestPrivateHelpers:
    """Direct tests of internal parsing helpers for result shapes Bandit's
    real output doesn't currently produce but its JSON schema doesn't rule
    out (an evolving external tool's output is untrusted, ADR-0004).
    """

    def test_raw_fields_skips_absent_keys(self) -> None:
        assert _raw_fields({"test_name": "x"}) == {"test_name": "x"}

    def test_raw_fields_skips_a_non_list_line_range(self) -> None:
        assert "line_range" not in _raw_fields({"line_range": "not-a-list"})

    def test_location_for_falls_back_to_the_raw_filename_outside_root(self) -> None:
        result = {
            "filename": "/completely/unrelated/path.py",
            "line_number": 1,
            "col_offset": 0,
        }
        location = _location_for(result, root=Path("/some/other/root"))
        assert location.path == str(Path("/completely/unrelated/path.py"))

    def test_cwe_for_returns_none_when_issue_cwe_is_absent(self) -> None:
        assert _cwe_for({}) is None

    def test_cwe_for_returns_none_when_issue_cwe_id_is_not_an_int(self) -> None:
        assert _cwe_for({"issue_cwe": {"id": "not-an-int"}}) is None
