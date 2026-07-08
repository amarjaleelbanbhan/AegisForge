"""The `RunManifest` provenance record (evaluation-framework.md §5).

Every benchmark (or production) run persists an immutable `RunManifest`
sufficient to reproduce it: the exact code, config, dataset, models,
prompts, runtime/hardware, cost, and resulting metrics. Manifests are the
unit of comparison across runs — a metric without a manifest recording how
it was produced is not a reproducible research claim.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    """Base for immutable, strictly-validated evaluation records.

    Mirrors `cortexward.domain.models._Frozen` — a run manifest is exactly
    the kind of adversarial-adjacent, audit-critical record that benefits
    from rejecting unknown fields and forbidding post-construction mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class DatasetRef(_Frozen):
    """The versioned dataset a run was evaluated against."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ModelRef(_Frozen):
    """One model used somewhere in a run (there may be several, per task)."""

    task: str = Field(min_length=1, description="e.g. 'reasoning', 'repair'.")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    version: str = Field(min_length=1)
    training_cutoff: str | None = None
    """ISO date string, if known — needed to classify the contamination split
    (evaluation-framework.md §4.2) a finding falls into for this model."""


class RuntimeInfo(_Frozen):
    """When a run started and how long it took, end to end."""

    started: datetime
    wall_seconds: float = Field(ge=0)


class HardwareInfo(_Frozen):
    """What a run executed on — part of reproducibility, not just curiosity."""

    cpu: str = Field(min_length=1)
    gpu: str | None = None
    ram_gb: float | None = Field(default=None, gt=0)
    os: str = Field(min_length=1)


class CostInfo(_Frozen):
    """Token usage and estimated spend for a run."""

    tokens_prompt: int = Field(default=0, ge=0)
    tokens_completion: int = Field(default=0, ge=0)
    usd_estimate: float = Field(default=0.0, ge=0)


class DetectionMetrics(_Frozen):
    """The metrics block (evaluation-framework.md §2) recorded per run.

    Only detection-quality metrics (§2.1) are required; verification and
    patch-quality metrics (§2.2, §2.3) are optional until the ladder stages
    and patch pipeline that produce them exist (later phases) — recording
    `None` is honest, not a placeholder value pretending to be data.
    """

    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    fpr: float = Field(ge=0, le=1, description="FP / (FP + TP) — see cortexward.eval.metrics.")
    fnr: float = Field(ge=0, le=1, description="FN / (FN + TP) — see cortexward.eval.metrics.")
    verification_success_by_rung: dict[str, float] = Field(default_factory=dict)
    patch_correctness: float | None = Field(default=None, ge=0, le=1)
    regression_rate: float | None = Field(default=None, ge=0, le=1)
    brier: float | None = Field(default=None, ge=0, le=1)


class RunManifest(_Frozen):
    """The complete, immutable record of one evaluation (or production) run."""

    run_id: str = Field(min_length=1)
    git_sha: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    calibration_profile: str = Field(min_length=1)
    dataset: DatasetRef
    models: tuple[ModelRef, ...] = Field(default_factory=tuple)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    runtime: RuntimeInfo
    hardware: HardwareInfo
    cost: CostInfo = Field(default_factory=CostInfo)
    metrics: DetectionMetrics
