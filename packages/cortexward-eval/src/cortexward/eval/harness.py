"""Turns scan findings + a `Dataset` into a `RunManifest` (evaluation-framework.md §5-7).

Deliberately takes already-produced `Finding`s rather than running scanners
itself: this package stays isolated from every adapter (the "evaluation
harness does not depend on other adapters" import-linter contract), so the
actual scanning is the caller's job (`ward bench run`, `cortexward-cli`) —
this module is only about turning scan output into metrics, a manifest, and
per-example detection outcomes for the statistical protocol (§6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from cortexward.domain import Finding
from cortexward.eval.dataset import Dataset
from cortexward.eval.manifest import DatasetRef, HardwareInfo, RunManifest, RuntimeInfo
from cortexward.eval.metrics import detection_metrics, match_findings


def run_bench(
    dataset: Dataset,
    findings: Sequence[Finding],
    *,
    run_id: str,
    git_sha: str,
    config_hash: str,
    calibration_profile: str,
    started: datetime,
    wall_seconds: float,
    hardware: HardwareInfo,
) -> tuple[RunManifest, Mapping[str, bool]]:
    """Matches `findings` against `dataset`'s ground truth and builds a `RunManifest`.

    Returns the manifest alongside a per-example "was it detected" map, one
    entry per example that actually carries ground truth (a true-negative
    example has no "detected" concept — it either kept the run's precision
    intact or it didn't, which `RunManifest.metrics` already captures via
    `fpr`). The per-example map is what `ward bench compare` needs for
    McNemar's test (§6) on matched detection outcomes between two runs;
    `RunManifest` itself only ever carries aggregate metrics, matching
    evaluation-framework.md §5's own documented shape exactly.
    """
    ground_truth = tuple(gt for example in dataset.examples for gt in example.ground_truth)
    match = match_findings(findings, ground_truth)
    matched_truth_ids = {truth_id for _, truth_id in match.true_positives}
    per_example_detected = {
        example.id: any(gt.id in matched_truth_ids for gt in example.ground_truth)
        for example in dataset.examples
        if example.ground_truth
    }
    manifest = RunManifest(
        run_id=run_id,
        git_sha=git_sha,
        config_hash=config_hash,
        calibration_profile=calibration_profile,
        dataset=DatasetRef(name=dataset.name, version=dataset.version),
        runtime=RuntimeInfo(started=started, wall_seconds=wall_seconds),
        hardware=hardware,
        metrics=detection_metrics(match),
    )
    return manifest, per_example_detected


__all__ = ["run_bench"]
