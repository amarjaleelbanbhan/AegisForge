"""Unit tests for the `ward` CLI.

Uses `typer.testing.CliRunner` to invoke the real `scan` command end to end
(real `BanditScanner`/`SecretsScanner` against fixture files, no mocking),
consistent with this codebase's preference for real integration tests.
"""

from __future__ import annotations

import json
import runpy
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.error import URLError

import pytest
from typer.testing import CliRunner

from cortexward.cli import app, main

pytestmark = pytest.mark.unit

runner = CliRunner()

_LIVE_OLLAMA_URL = "http://localhost:11434"
_LIVE_MODEL = "qwen2.5-coder:7b"


def _ollama_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{_LIVE_OLLAMA_URL}/api/tags", timeout=2):  # noqa: S310 # nosec B310
            return True
    except (URLError, TimeoutError, OSError):
        return False


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


class TestLlmVerification:
    def test_no_llm_flags_behaves_exactly_as_before(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "none"])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        properties = document["runs"][0]["results"][0]["properties"]
        assert properties["state"] == "candidate"

    def test_llm_provider_without_model_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--llm-provider", "ollama"])
        assert result.exit_code != 0

    def test_invalid_llm_provider_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(
            app,
            ["scan", str(tmp_path), "--llm-provider", "not-a-real-provider", "--llm-model", "x"],
        )
        assert result.exit_code != 0

    def test_llm_config_and_llm_provider_together_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        config_path = tmp_path / "llm.yaml"
        config_path.write_text("provider: ollama\nmodel: qwen2.5-coder:7b\n", encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "scan",
                str(tmp_path),
                "--llm-config",
                str(config_path),
                "--llm-provider",
                "ollama",
                "--llm-model",
                "qwen2.5-coder:7b",
            ],
        )
        assert result.exit_code != 0

    def test_nonexistent_llm_config_path_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(
            app, ["scan", str(tmp_path), "--llm-config", str(tmp_path / "missing.yaml")]
        )
        assert result.exit_code != 0

    def test_malformed_llm_config_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        config_path = tmp_path / "llm.yaml"
        config_path.write_text("provider: ollama\n", encoding="utf-8")  # missing required model
        result = runner.invoke(app, ["scan", str(tmp_path), "--llm-config", str(config_path)])
        assert result.exit_code != 0

    @pytest.mark.integration
    @pytest.mark.skipif(not _ollama_is_running(), reason="no local Ollama server reachable")
    def test_llm_provider_ollama_runs_the_agent_pipeline_end_to_end(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            'import subprocess\n\nif __name__ == "__main__":\n'
            '    subprocess.call("echo hi", shell=True)\n',
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "scan",
                str(tmp_path),
                "--fail-on",
                "none",
                "--llm-provider",
                "ollama",
                "--llm-model",
                _LIVE_MODEL,
            ],
        )
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert len(document["runs"][0]["results"]) >= 1


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
