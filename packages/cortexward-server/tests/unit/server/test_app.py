"""Unit tests for the CortexWard REST API.

Uses FastAPI's `TestClient` to invoke the real app end to end (real
`BanditScanner`/`SecretsScanner` against fixture files, no mocking),
consistent with this codebase's preference for real integration tests.
`TestClient` runs `BackgroundTasks` synchronously before a request
completes (verified empirically before writing these tests, not assumed),
so a scan job is already "completed" by the time `client.post(...)`
returns — no polling loop is needed here.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import cast
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from cortexward.llm import LLMProviderConfig, Provider
from cortexward.orchestrator import SequentialOrchestrator
from cortexward.server.app import app

pytestmark = pytest.mark.unit

client = TestClient(app)

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


class TestCreateScan:
    def test_returns_202_with_a_job_id(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        response = client.post("/v1/scans", json={"root": str(tmp_path)})
        assert response.status_code == 202
        body = response.json()
        assert body["id"].startswith("job_")

    def test_job_completes_by_the_time_the_request_returns(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        response = client.post("/v1/scans", json={"root": str(tmp_path)})
        job_id = response.json()["id"]
        status = client.get(f"/v1/scans/{job_id}")
        assert status.json()["status"] == "completed"

    def test_nonexistent_root_returns_422(self, tmp_path: Path) -> None:
        response = client.post("/v1/scans", json={"root": str(tmp_path / "missing")})
        assert response.status_code == 422

    def test_a_file_root_returns_422(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not_a_dir.py"
        file_path.write_text("x = 1\n")
        response = client.post("/v1/scans", json={"root": str(file_path)})
        assert response.status_code == 422

    def test_llm_provider_without_model_returns_422(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        response = client.post("/v1/scans", json={"root": str(tmp_path), "llm_provider": "ollama"})
        assert response.status_code == 422

    def test_invalid_llm_provider_returns_422(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        response = client.post(
            "/v1/scans",
            json={"root": str(tmp_path), "llm_provider": "not-a-real-provider", "llm_model": "x"},
        )
        assert response.status_code == 422

    def test_missing_root_field_returns_422(self) -> None:
        response = client.post("/v1/scans", json={})
        assert response.status_code == 422

    def test_valid_llm_provider_and_model_resolve_a_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Confirms the LLMProviderConfig build_pipeline() receives is
        # correctly resolved, without needing a live LLM backend: swap in a
        # fake build_pipeline that just records what it was called with and
        # returns a real (no-op) SequentialOrchestrator.
        _write_clean_file(tmp_path)
        captured: dict[str, object] = {}

        def _fake_build_pipeline(**kwargs: object) -> SequentialOrchestrator:
            captured.update(kwargs)
            return SequentialOrchestrator(scanners=())

        monkeypatch.setattr("cortexward.server.app.build_pipeline", _fake_build_pipeline)
        response = client.post(
            "/v1/scans",
            json={"root": str(tmp_path), "llm_provider": "ollama", "llm_model": "qwen2.5-coder:7b"},
        )
        assert response.status_code == 202
        llm_config = cast("LLMProviderConfig", captured["llm_config"])
        assert llm_config.provider == Provider.OLLAMA
        assert llm_config.model == "qwen2.5-coder:7b"

    def test_a_scan_failure_marks_the_job_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_clean_file(tmp_path)

        def _raise(**_kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr("cortexward.server.app.build_pipeline", _raise)
        response = client.post("/v1/scans", json={"root": str(tmp_path)})
        job_id = response.json()["id"]
        status = client.get(f"/v1/scans/{job_id}")
        assert status.json()["status"] == "failed"
        assert "boom" in status.json()["error"]


class TestGetScan:
    def test_unknown_job_returns_404(self) -> None:
        response = client.get("/v1/scans/job_does_not_exist")
        assert response.status_code == 404

    def test_unknown_job_findings_returns_404(self) -> None:
        response = client.get("/v1/scans/job_does_not_exist/findings")
        assert response.status_code == 404


class TestGetScanFindings:
    def test_a_clean_directory_produces_no_findings(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        job_id = client.post("/v1/scans", json={"root": str(tmp_path)}).json()["id"]
        findings = client.get(f"/v1/scans/{job_id}/findings")
        assert findings.status_code == 200
        assert findings.json()["findings"] == []

    def test_a_vulnerable_file_produces_a_finding(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        job_id = client.post("/v1/scans", json={"root": str(tmp_path)}).json()["id"]
        findings = client.get(f"/v1/scans/{job_id}/findings").json()["findings"]
        assert len(findings) >= 1
        assert any(finding["rule_id"] == "B602" for finding in findings)

    def test_findings_carry_the_full_finding_shape_not_just_sarif_fields(
        self, tmp_path: Path
    ) -> None:
        _write_vulnerable_file(tmp_path)
        job_id = client.post("/v1/scans", json={"root": str(tmp_path)}).json()["id"]
        findings = client.get(f"/v1/scans/{job_id}/findings").json()["findings"]
        finding = next(f for f in findings if f["rule_id"] == "B602")
        assert "evidence" in finding
        assert "provenance" in finding
        assert finding["state"] == "candidate"

    def test_no_llm_provider_leaves_findings_unverified(self, tmp_path: Path) -> None:
        _write_vulnerable_file(tmp_path)
        job_id = client.post("/v1/scans", json={"root": str(tmp_path)}).json()["id"]
        findings = client.get(f"/v1/scans/{job_id}/findings").json()["findings"]
        assert all(f["state"] == "candidate" for f in findings)

    def test_language_filter_is_accepted(self, tmp_path: Path) -> None:
        _write_clean_file(tmp_path)
        response = client.post("/v1/scans", json={"root": str(tmp_path), "languages": ["python"]})
        assert response.status_code == 202


@pytest.mark.integration
@pytest.mark.skipif(not _ollama_is_running(), reason="no local Ollama server reachable")
class TestLiveOllamaScan:
    def test_llm_provider_runs_the_agent_pipeline_end_to_end(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            'import subprocess\n\nif __name__ == "__main__":\n'
            '    subprocess.call("echo hi", shell=True)\n',
            encoding="utf-8",
        )
        response = client.post(
            "/v1/scans",
            json={
                "root": str(tmp_path),
                "languages": ["python"],
                "llm_provider": "ollama",
                "llm_model": _LIVE_MODEL,
            },
        )
        job_id = response.json()["id"]
        status = client.get(f"/v1/scans/{job_id}")
        assert status.json()["status"] == "completed"
        findings = client.get(f"/v1/scans/{job_id}/findings").json()["findings"]
        assert len(findings) >= 1
        finding = next(f for f in findings if any(loc["start_line"] == 4 for loc in f["locations"]))
        assert any(e["kind"] == "reachability_proof" for e in finding["evidence"])
