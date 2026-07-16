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
import uvicorn
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


class TestReportFormat:
    def test_default_format_is_sarif(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "none"])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert document["version"] == "2.1.0"

    def test_cortexward_json_format_renders_the_full_finding(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(
            app, ["scan", str(tmp_path), "--format", "cortexward-json", "--fail-on", "none"]
        )
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert "cortexward_version" in document
        assert len(document["findings"]) >= 1
        assert "evidence" in document["findings"][0]

    def test_cortexward_json_format_writes_to_an_output_file(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        output_path = tmp_path / "out.json"
        result = runner.invoke(
            app,
            [
                "scan",
                str(tmp_path),
                "--format",
                "cortexward-json",
                "--output",
                str(output_path),
                "--fail-on",
                "none",
            ],
        )
        assert result.exit_code == 0
        document = json.loads(output_path.read_text())
        assert "findings" in document

    def test_unknown_format_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--format", "not-a-real-format"])
        assert result.exit_code != 0


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


class TestBaselineOption:
    """The baseline file itself is written *outside* the scanned directory in
    these tests — not just for tidiness. `ward scan` walks every file under
    its target root including any baseline sitting inside it, and a baseline
    file's own fingerprint hashes are exactly the kind of high-entropy hex
    string detect-secrets flags as a possible secret, producing a spurious
    new finding that (correctly) isn't suppressed since it postdates the
    baseline it would need to appear in."""

    def test_baseline_suppresses_a_previously_recorded_finding(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        _write_vulnerable_file(target)
        baseline_path = tmp_path / "baseline.json"
        generate_result = runner.invoke(
            app, ["baseline", str(target), "--output", str(baseline_path)]
        )
        assert generate_result.exit_code == 0
        assert baseline_path.exists()

        scan_result = runner.invoke(
            app, ["scan", str(target), "--baseline", str(baseline_path), "--fail-on", "none"]
        )
        assert scan_result.exit_code == 0
        document = json.loads(scan_result.stdout)
        assert document["runs"][0]["results"] == []

    def test_baseline_does_not_suppress_the_fail_on_exit_code_for_new_findings(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        _write_clean_file(target)
        baseline_path = tmp_path / "baseline.json"
        generate_result = runner.invoke(
            app, ["baseline", str(target), "--output", str(baseline_path)]
        )
        assert generate_result.exit_code == 0

        _write_vulnerable_file(target)
        scan_result = runner.invoke(
            app, ["scan", str(target), "--baseline", str(baseline_path)]
        )
        assert scan_result.exit_code == 1

    def test_nonexistent_baseline_path_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(
            app, ["scan", str(tmp_path), "--baseline", str(tmp_path / "missing.json")]
        )
        assert result.exit_code != 0


class TestBaselineCommand:
    def test_generates_a_baseline_file_recording_current_findings(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        output_path = tmp_path / "baseline.json"
        result = runner.invoke(app, ["baseline", str(tmp_path), "--output", str(output_path)])
        assert result.exit_code == 0
        document = json.loads(output_path.read_text())
        assert len(document["suppressions"]) >= 1
        assert document["suppressions"][0]["fingerprint"]

    def test_default_output_path_is_cortexward_baseline_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_vulnerable_file(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["baseline", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "cortexward-baseline.json").exists()

    def test_custom_reason_is_recorded_on_every_entry(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        output_path = tmp_path / "baseline.json"
        result = runner.invoke(
            app,
            [
                "baseline",
                str(tmp_path),
                "--output",
                str(output_path),
                "--reason",
                "known false positive in fixture",
            ],
        )
        assert result.exit_code == 0
        document = json.loads(output_path.read_text())
        assert document["suppressions"][0]["reason"] == "known false positive in fixture"

    def test_a_clean_directory_produces_an_empty_baseline(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        output_path = tmp_path / "baseline.json"
        result = runner.invoke(app, ["baseline", str(tmp_path), "--output", str(output_path)])
        assert result.exit_code == 0
        document = json.loads(output_path.read_text())
        assert document["suppressions"] == []


class TestServeCommand:
    """`serve` delegates to `uvicorn.run` -- monkeypatched here so tests don't
    actually bind a port and block; the wiring itself (which module:attr
    string, which host/port/reload) is what's under test."""

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _fake_run(target: str, **kwargs: object) -> None:
            captured.update({"target": target, **kwargs})

        monkeypatch.setattr(uvicorn, "run", _fake_run)
        result = runner.invoke(app, ["serve"])
        assert result.exit_code == 0
        assert captured["target"] == "cortexward.server.app:app"
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8000
        assert captured["reload"] is False

    def test_custom_host_port_and_reload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _fake_run(target: str, **kwargs: object) -> None:
            captured.update({"target": target, **kwargs})

        monkeypatch.setattr(uvicorn, "run", _fake_run)
        result = runner.invoke(
            app,
            ["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"],  # noqa: S104
        )
        assert result.exit_code == 0
        assert captured["host"] == "0.0.0.0"  # noqa: S104
        assert captured["port"] == 9000
        assert captured["reload"] is True


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
