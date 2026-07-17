"""Conformance test for the Orchestrator port."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.domain import Provenance
from cortexward.ports import AnalysisRequest, OrchestratorPort, RunResult

pytestmark = pytest.mark.unit


class _FakeOrchestrator:
    def run(self, request: AnalysisRequest) -> RunResult:
        return RunResult(run_id="run_1", findings=(), patches=())


def test_fake_orchestrator_satisfies_protocol() -> None:
    assert isinstance(_FakeOrchestrator(), OrchestratorPort)


def test_run_returns_result_for_request(tmp_path: Path) -> None:
    request = AnalysisRequest(root=tmp_path, languages=("python",))
    result = _FakeOrchestrator().run(request)
    assert result.run_id == "run_1"
    assert result.findings == ()


def test_analysis_request_config_defaults_are_independent() -> None:
    r1 = AnalysisRequest(root=Path("."))
    r2 = AnalysisRequest(root=Path("."))
    assert r1.config is not r2.config
    assert r1.config == {}


def test_provenance_still_importable_from_domain() -> None:
    # Sanity: ports depend on domain, not the reverse (import-linter enforces this).
    assert Provenance(producer="orchestrator").producer == "orchestrator"
