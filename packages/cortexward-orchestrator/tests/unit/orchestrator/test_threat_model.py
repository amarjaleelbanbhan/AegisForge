"""Unit tests for `build_threat_model_for`.

Runs the real scanner pipeline and the real CPG builder against fixture
files, consistent with this codebase's preference for real integration
tests over mocked scanners/graphs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.domain import StrideCategory, ThreatModel
from cortexward.orchestrator import build_threat_model_for

pytestmark = pytest.mark.unit


def _write_vulnerable_file(tmp_path: Path) -> None:
    (tmp_path / "vuln.py").write_text(
        "import subprocess\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n"
    )


def _write_clean_file(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("def add(a, b):\n    return a + b\n")


class TestBuildThreatModelFor:
    def test_returns_a_threat_model(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        model = build_threat_model_for(root=tmp_path)
        assert isinstance(model, ThreatModel)

    def test_a_clean_directory_yields_no_threats(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        model = build_threat_model_for(root=tmp_path)
        assert model.threats == ()

    def test_a_command_injection_finding_becomes_a_tampering_threat(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        model = build_threat_model_for(root=tmp_path)
        assert len(model.threats) >= 1
        assert any(StrideCategory.TAMPERING in threat.categories for threat in model.threats)

    def test_no_reachability_leaves_every_threat_unreachable(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        model = build_threat_model_for(root=tmp_path, reachability=False)
        assert model.threats
        assert model.exposed == ()

    def test_a_directly_reachable_vulnerable_call_is_marked_exposed(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            'import subprocess\n\nif __name__ == "__main__":\n'
            '    subprocess.call("echo hi", shell=True)\n',
            encoding="utf-8",
        )
        model = build_threat_model_for(root=tmp_path, reachability=True)
        assert model.exposed

    def test_language_filter_is_accepted(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        model = build_threat_model_for(root=tmp_path, languages=("python",))
        assert isinstance(model, ThreatModel)
