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

__all__ = [
    "CostInfo",
    "DatasetRef",
    "DetectionMetrics",
    "GroundTruthFinding",
    "HardwareInfo",
    "MatchResult",
    "ModelRef",
    "RunManifest",
    "RuntimeInfo",
    "detection_metrics",
    "f1_score",
    "false_negative_rate",
    "false_positive_rate",
    "match_findings",
    "precision",
    "recall",
]
