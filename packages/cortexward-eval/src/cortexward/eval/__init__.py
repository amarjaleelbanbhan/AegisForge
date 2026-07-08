"""CortexWard's benchmark-first evaluation harness (MPS §23, ADR-0007)."""

from __future__ import annotations

from cortexward.eval.manifest import (
    CostInfo,
    DatasetRef,
    DetectionMetrics,
    HardwareInfo,
    ModelRef,
    RunManifest,
    RuntimeInfo,
)
from cortexward.eval.metrics import (
    GroundTruthFinding,
    MatchResult,
    detection_metrics,
    f1_score,
    false_negative_rate,
    false_positive_rate,
    match_findings,
    precision,
    recall,
)
from cortexward.eval.statistics import (
    ConfidenceInterval,
    McNemarResult,
    bootstrap_ci,
    mcnemar_test,
)

__all__ = [
    "ConfidenceInterval",
    "CostInfo",
    "DatasetRef",
    "DetectionMetrics",
    "GroundTruthFinding",
    "HardwareInfo",
    "MatchResult",
    "McNemarResult",
    "ModelRef",
    "RunManifest",
    "RuntimeInfo",
    "bootstrap_ci",
    "detection_metrics",
    "f1_score",
    "false_negative_rate",
    "false_positive_rate",
    "match_findings",
    "mcnemar_test",
    "precision",
    "recall",
]
