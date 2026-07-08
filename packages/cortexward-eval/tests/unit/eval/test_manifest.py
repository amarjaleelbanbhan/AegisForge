"""Unit tests for the RunManifest provenance record."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cortexward.eval import (
    CostInfo,
    DatasetRef,
    DetectionMetrics,
    HardwareInfo,
    ModelRef,
    RunManifest,
    RuntimeInfo,
)

pytestmark = pytest.mark.unit


def _manifest(**overrides: object) -> RunManifest:
    defaults: dict[str, object] = {
        "run_id": "run_abc123",
        "git_sha": "deadbeef",
        "config_hash": "cfg_hash",
        "calibration_profile": "default@1",
        "dataset": DatasetRef(name="ward-bench", version="2026.07"),
        "runtime": RuntimeInfo(started=datetime.now(UTC), wall_seconds=12.5),
        "hardware": HardwareInfo(cpu="x86_64", os="linux"),
        "metrics": DetectionMetrics(precision=0.9, recall=0.8, f1=0.847, fpr=0.1, fnr=0.2),
    }
    defaults.update(overrides)
    return RunManifest(**defaults)  # type: ignore[arg-type]


class TestRunManifest:
    def test_builds_with_required_fields(self) -> None:
        manifest = _manifest()
        assert manifest.run_id == "run_abc123"
        assert manifest.dataset.name == "ward-bench"
        assert manifest.cost == CostInfo()
        assert manifest.models == ()
        assert manifest.prompt_versions == {}

    def test_is_frozen(self) -> None:
        manifest = _manifest()
        with pytest.raises(ValidationError):
            manifest.run_id = "changed"  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(unexpected_field="oops")

    def test_carries_model_refs(self) -> None:
        model = ModelRef(
            task="reasoning",
            provider="anthropic",
            model="claude",
            version="5",
            training_cutoff="2026-01",
        )
        manifest = _manifest(models=(model,))
        assert manifest.models == (model,)

    def test_carries_cost_info(self) -> None:
        cost = CostInfo(tokens_prompt=100, tokens_completion=50, usd_estimate=0.01)
        manifest = _manifest(cost=cost)
        assert manifest.cost.tokens_prompt == 100


class TestDetectionMetrics:
    def test_rejects_out_of_range_precision(self) -> None:
        with pytest.raises(ValidationError):
            DetectionMetrics(precision=1.5, recall=0.5, f1=0.5, fpr=0.1, fnr=0.1)

    def test_optional_fields_default_to_none(self) -> None:
        metrics = DetectionMetrics(precision=0.5, recall=0.5, f1=0.5, fpr=0.5, fnr=0.5)
        assert metrics.patch_correctness is None
        assert metrics.regression_rate is None
        assert metrics.brier is None
        assert metrics.verification_success_by_rung == {}


class TestHardwareInfo:
    def test_rejects_non_positive_ram(self) -> None:
        with pytest.raises(ValidationError):
            HardwareInfo(cpu="x86_64", os="linux", ram_gb=0)

    def test_gpu_defaults_to_none(self) -> None:
        hardware = HardwareInfo(cpu="x86_64", os="linux")
        assert hardware.gpu is None
