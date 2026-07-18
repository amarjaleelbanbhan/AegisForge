"""Unit tests for the `ward` CLI.

Uses `typer.testing.CliRunner` to invoke the real `scan` command end to end
(real `BanditScanner`/`SecretsScanner` against fixture files, no mocking),
consistent with this codebase's preference for real integration tests.
"""

from __future__ import annotations

import importlib
import json
import runpy
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.error import URLError

import pytest
import uvicorn
from typer.testing import CliRunner

from cortexward.cli import app, main
from cortexward.llm import LLMProviderConfig, Provider
from cortexward.orchestrator import SequentialOrchestrator

# `cortexward.cli.main` (the submodule) and `main` (the CLI entry-point
# function re-exported from it in cortexward/cli/__init__.py, imported
# above) share a name; that re-export rebinds the *attribute*
# `cortexward.cli.main` from "the submodule" to "the function" (Python's
# `import a.b.c as x` resolves via attribute traversal from `a`, not via
# `sys.modules`, so it's affected by this too) — `importlib.import_module`
# is the one route that reliably returns the real module regardless.
_cli_main_module = importlib.import_module("cortexward.cli.main")

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

    def test_valid_llm_provider_and_model_resolve_a_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exercises _resolve_llm_config's success path deterministically,
        # without a live LLM backend: swap in a fake build_pipeline that
        # just records what it was called with and returns a real (no-op)
        # SequentialOrchestrator. The end-to-end test below covers the same
        # path against a real Ollama server, but it's skipped whenever none
        # is reachable (always true in CI), so this is the only path this
        # branch is covered by there.
        _write_clean_file(tmp_path)
        captured: dict[str, object] = {}

        def _fake_build_pipeline(**kwargs: object) -> SequentialOrchestrator:
            captured.update(kwargs)
            return SequentialOrchestrator(scanners=())

        monkeypatch.setattr(_cli_main_module, "build_pipeline", _fake_build_pipeline)
        result = runner.invoke(
            app,
            [
                "scan",
                str(tmp_path),
                "--llm-provider",
                "ollama",
                "--llm-model",
                "qwen2.5-coder:7b",
                "--fail-on",
                "none",
            ],
        )
        assert result.exit_code == 0
        llm_config = captured["llm_config"]
        assert isinstance(llm_config, LLMProviderConfig)
        assert llm_config.provider == Provider.OLLAMA
        assert llm_config.model == "qwen2.5-coder:7b"

    def test_invalid_engine_is_rejected(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["scan", str(tmp_path), "--engine", "not-a-real-engine"])
        assert result.exit_code != 0

    def test_default_engine_is_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_clean_file(tmp_path)
        captured: dict[str, object] = {}

        def _fake_build_pipeline(**kwargs: object) -> SequentialOrchestrator:
            captured.update(kwargs)
            return SequentialOrchestrator(scanners=())

        monkeypatch.setattr(_cli_main_module, "build_pipeline", _fake_build_pipeline)
        result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "none"])
        assert result.exit_code == 0
        assert captured["engine"] == "agent"

    def test_engine_langgraph_is_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_clean_file(tmp_path)
        captured: dict[str, object] = {}

        def _fake_build_pipeline(**kwargs: object) -> SequentialOrchestrator:
            captured.update(kwargs)
            return SequentialOrchestrator(scanners=())

        monkeypatch.setattr(_cli_main_module, "build_pipeline", _fake_build_pipeline)
        result = runner.invoke(
            app, ["scan", str(tmp_path), "--fail-on", "none", "--engine", "langgraph"]
        )
        assert result.exit_code == 0
        assert captured["engine"] == "langgraph"

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
        scan_result = runner.invoke(app, ["scan", str(target), "--baseline", str(baseline_path)])
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


class TestThreatModelCommand:
    def test_prints_a_stride_categorized_threat_model_to_stdout(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["threat-model", str(tmp_path)])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert len(document["threats"]) >= 1
        assert document["threats"][0]["categories"]

    def test_a_clean_directory_yields_no_threats(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["threat-model", str(tmp_path)])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert document["threats"] == []

    def test_writes_to_an_output_file_when_given(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        output_path = tmp_path / "threats.json"
        result = runner.invoke(app, ["threat-model", str(tmp_path), "--output", str(output_path)])
        assert result.exit_code == 0
        assert output_path.exists()
        document = json.loads(output_path.read_text())
        assert len(document["threats"]) >= 1

    def test_no_reachability_still_produces_threats(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        result = runner.invoke(app, ["threat-model", str(tmp_path), "--no-reachability"])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert document["threats"]
        assert all(t["reachable_from_entrypoint"] is False for t in document["threats"])

    def test_a_directly_reachable_call_is_marked_exposed(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            'import subprocess\n\nif __name__ == "__main__":\n'
            '    subprocess.call("echo hi", shell=True)\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["threat-model", str(tmp_path)])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert any(t["reachable_from_entrypoint"] is True for t in document["threats"])

    def test_language_filter_is_accepted(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        result = runner.invoke(app, ["threat-model", str(tmp_path), "--language", "python"])
        assert result.exit_code == 0

    def test_default_path_is_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_clean_file(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["threat-model"])
        assert result.exit_code == 0

    def test_nonexistent_path_is_rejected(self) -> None:
        result = runner.invoke(app, ["threat-model", "/definitely/does/not/exist"])
        assert result.exit_code != 0


def _write_bench_dataset(tmp_path: Path) -> Path:
    """A tiny, self-contained dataset: one real vulnerable example, one
    true-negative example, ground truth matching real Bandit output
    exactly (empirically verified the same way the shipped golden dataset
    under packages/cortexward-eval/datasets/golden/v1 was)."""
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "vuln.py").write_text(
        "import subprocess\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n",
        encoding="utf-8",
    )
    (examples_dir / "clean.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "cli-test-dataset",
                "version": "v1",
                "split": "novel",
                "examples": [
                    {
                        "id": "vuln",
                        "path": "examples/vuln.py",
                        "ground_truth": [
                            {
                                "id": "vuln-import",
                                "location": {"path": "examples/vuln.py", "start_line": 1},
                                "cwe": 78,
                            },
                            {
                                "id": "vuln-shell-true",
                                "location": {"path": "examples/vuln.py", "start_line": 3},
                                "cwe": 78,
                            },
                        ],
                    },
                    {"id": "clean", "path": "examples/clean.py", "ground_truth": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


class TestBenchRunCommand:
    def test_writes_a_run_manifest_with_perfect_metrics(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        output_path = tmp_path / "run.json"
        result = runner.invoke(
            app, ["bench", "run", str(manifest_path), "--output", str(output_path)]
        )
        assert result.exit_code == 0, result.output
        document = json.loads(output_path.read_text())
        assert document["metrics"]["precision"] == 1.0
        assert document["metrics"]["recall"] == 1.0
        assert document["dataset"] == {"name": "cli-test-dataset", "version": "v1"}

    def test_writes_a_companion_matches_file(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        output_path = tmp_path / "run.json"
        result = runner.invoke(
            app, ["bench", "run", str(manifest_path), "--output", str(output_path)]
        )
        assert result.exit_code == 0, result.output
        matches_path = tmp_path / "run.json.matches.json"
        assert matches_path.exists()
        assert json.loads(matches_path.read_text()) == {"vuln": True}

    def test_nonexistent_dataset_manifest_is_rejected(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["bench", "run", str(tmp_path / "nope.json"), "--output", str(tmp_path / "o.json")]
        )
        assert result.exit_code != 0

    def test_git_sha_unknown_when_git_is_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only stubs `_git_sha`'s own call, not `subprocess.run` globally —
        # a global stub would also break the real Bandit/Semgrep subprocess
        # calls this test's scan step depends on.
        real_run = subprocess.run

        def _selective_run(argv: list[str], **kwargs: object) -> object:
            if argv and argv[0] == "git":
                raise FileNotFoundError("git not found")
            return real_run(argv, **kwargs)  # type: ignore[call-overload]

        monkeypatch.setattr("cortexward.cli.bench.subprocess.run", _selective_run)
        manifest_path = _write_bench_dataset(tmp_path)
        output_path = tmp_path / "run.json"
        result = runner.invoke(
            app, ["bench", "run", str(manifest_path), "--output", str(output_path)]
        )
        assert result.exit_code == 0, result.output
        document = json.loads(output_path.read_text())
        assert document["git_sha"] == "unknown"


class TestBenchReportCommand:
    def test_default_markdown_report_to_stdout(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_path = tmp_path / "run.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_path)])
        result = runner.invoke(app, ["bench", "report", str(run_path)])
        assert result.exit_code == 0
        assert "# Benchmark report" in result.output
        assert "| Precision | 1.000 |" in result.output

    def test_json_format(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_path = tmp_path / "run.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_path)])
        result = runner.invoke(app, ["bench", "report", str(run_path), "--format", "json"])
        assert result.exit_code == 0
        document = json.loads(result.output)
        assert document["metrics"]["precision"] == 1.0

    def test_writes_to_an_output_file(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_path = tmp_path / "run.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_path)])
        report_path = tmp_path / "report.md"
        result = runner.invoke(
            app, ["bench", "report", str(run_path), "--output", str(report_path)]
        )
        assert result.exit_code == 0
        assert "# Benchmark report" in report_path.read_text()

    def test_invalid_format_is_rejected(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_path = tmp_path / "run.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_path)])
        result = runner.invoke(app, ["bench", "report", str(run_path), "--format", "yaml"])
        assert result.exit_code != 0

    def test_multiple_formats_to_stdout_are_each_labeled(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_path = tmp_path / "run.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_path)])
        result = runner.invoke(app, ["bench", "report", str(run_path), "--format", "md,json"])
        assert result.exit_code == 0
        assert "=== md ===" in result.output
        assert "=== json ===" in result.output

    def test_multiple_formats_to_output_write_one_file_per_format(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_path = tmp_path / "run.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_path)])
        output_path = tmp_path / "report.out"
        result = runner.invoke(
            app,
            ["bench", "report", str(run_path), "--format", "md,json", "--output", str(output_path)],
        )
        assert result.exit_code == 0
        assert output_path.with_suffix(".md").exists()
        assert output_path.with_suffix(".json").exists()


class TestBenchCompareCommand:
    def test_compares_two_runs_of_the_same_dataset(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_a = tmp_path / "run_a.json"
        run_b = tmp_path / "run_b.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_a)])
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_b)])
        result = runner.invoke(app, ["bench", "compare", str(run_a), str(run_b)])
        assert result.exit_code == 0
        assert "precision" in result.output
        assert "McNemar" in result.output
        assert "0 discordant" in result.output

    def test_nonexistent_manifest_is_rejected(self, tmp_path: Path) -> None:
        manifest_path = _write_bench_dataset(tmp_path)
        run_a = tmp_path / "run_a.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_a)])
        result = runner.invoke(app, ["bench", "compare", str(run_a), str(tmp_path / "no.json")])
        assert result.exit_code != 0

    def test_missing_companion_matches_files_skips_mcnemar(self, tmp_path: Path) -> None:
        # A hand-written RunManifest with no `.matches.json` sidecar (as if
        # produced some other way than `ward bench run`) -- comparison
        # still works on the aggregate metrics, just without McNemar.
        bare_manifest = json.dumps(
            {
                "run_id": "bench_bare",
                "git_sha": "deadbeef",
                "config_hash": "cfg",
                "calibration_profile": "static-default@1",
                "dataset": {"name": "bare", "version": "v1"},
                "runtime": {"started": "2026-01-01T00:00:00Z", "wall_seconds": 1.0},
                "hardware": {"cpu": "test", "os": "test"},
                "metrics": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "fpr": 0.0, "fnr": 0.0},
            }
        )
        run_a = tmp_path / "bare_a.json"
        run_b = tmp_path / "bare_b.json"
        run_a.write_text(bare_manifest, encoding="utf-8")
        run_b.write_text(bare_manifest, encoding="utf-8")
        result = runner.invoke(app, ["bench", "compare", str(run_a), str(run_b)])
        assert result.exit_code == 0
        assert "precision" in result.output
        assert "McNemar" not in result.output

    def test_no_shared_example_ids_skips_mcnemar(self, tmp_path: Path) -> None:
        # Two runs' matches.json sidecars both exist, but cover disjoint
        # example ids (e.g. two different datasets) -- nothing to pair.
        manifest_path = _write_bench_dataset(tmp_path)
        run_a = tmp_path / "run_a.json"
        runner.invoke(app, ["bench", "run", str(manifest_path), "--output", str(run_a)])

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "examples").mkdir()
        (other_dir / "examples" / "vuln2.py").write_text(
            "import subprocess\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n",
            encoding="utf-8",
        )
        other_manifest = other_dir / "manifest.json"
        other_manifest.write_text(
            json.dumps(
                {
                    "name": "other-dataset",
                    "version": "v1",
                    "split": "novel",
                    "examples": [
                        {
                            "id": "different-id",
                            "path": "examples/vuln2.py",
                            "ground_truth": [
                                {
                                    "id": "vuln2-import",
                                    "location": {"path": "examples/vuln2.py", "start_line": 1},
                                    "cwe": 78,
                                },
                                {
                                    "id": "vuln2-shell-true",
                                    "location": {"path": "examples/vuln2.py", "start_line": 3},
                                    "cwe": 78,
                                },
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        run_b = tmp_path / "run_b.json"
        runner.invoke(app, ["bench", "run", str(other_manifest), "--output", str(run_b)])

        result = runner.invoke(app, ["bench", "compare", str(run_a), str(run_b)])
        assert result.exit_code == 0
        assert "McNemar" not in result.output


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
