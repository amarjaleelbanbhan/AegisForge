"""Unit tests for the `ward` CLI.

Uses `typer.testing.CliRunner` to invoke the real `scan` command end to end
(real `BanditScanner`/`SecretsScanner` against fixture files, no mocking),
consistent with this codebase's preference for real integration tests.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cortexward.cli import app, main

pytestmark = pytest.mark.unit

runner = CliRunner()


def _write_vulnerable_file(tmp_path: Path) -> None:
    (tmp_path / "vuln.py").write_text(
        "import subprocess\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n"
    )


def _write_clean_file(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("def add(a, b):\n    return a + b\n")


class TestScanCommand:
    def test_requires_the_scan_subcommand_name(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, [str(tmp_path), "--fail-on", "none"])
        assert result.exit_code != 0

    def test_scan_prints_sarif_to_stdout_by_default(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "none"])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert document["version"] == "2.1.0"
        assert len(document["runs"][0]["results"]) >= 1

    def test_scan_writes_to_an_output_file_when_given(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        output_path = tmp_path / "out.sarif"
        result = runner.invoke(
            app, ["scan", str(tmp_path), "--output", str(output_path), "--fail-on", "none"]
        )
        assert result.exit_code == 0
        assert output_path.exists()
        document = json.loads(output_path.read_text())
        assert document["version"] == "2.1.0"

    def test_clean_directory_exits_zero_by_default(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 0

    def test_high_severity_finding_exits_nonzero_by_default(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 1

    def test_fail_on_none_never_fails_on_findings(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "none"])
        assert result.exit_code == 0

    def test_fail_on_critical_does_not_fail_on_a_high_severity_finding(
        self, tmp_path: Path
    ) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "critical"])
        assert result.exit_code == 0

    def test_invalid_fail_on_value_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "nonsense"])
        assert result.exit_code != 0

    def test_nonexistent_path_is_rejected(self) -> None:
        result = runner.invoke(app, ["scan", "/definitely/does/not/exist"])
        assert result.exit_code != 0

    def test_a_file_path_is_rejected_since_scan_expects_a_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not_a_dir.py"
        file_path.write_text("x = 1\n")
        result = runner.invoke(app, ["scan", str(file_path)])
        assert result.exit_code != 0

    def test_language_filter_is_accepted(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--language", "python"])
        assert result.exit_code == 0

    def test_default_path_is_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_clean_file(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["scan", "--fail-on", "none"])
        assert result.exit_code == 0


class TestEntryPoint:
    def test_main_invokes_the_typer_app(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["ward", "--help"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_module_executed_as_a_script_invokes_the_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["ward", "--help"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("cortexward.cli.main", run_name="__main__")
        assert exc_info.value.code == 0
