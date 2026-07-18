"""Unit tests for `cortexward.eval.harness.run_bench`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from cortexward.domain import Finding, SourceLocation
from cortexward.eval import (
    Dataset,
    DatasetExample,
    GroundTruthFinding,
    HardwareInfo,
    RunManifest,
    run_bench,
)

pytestmark = pytest.mark.unit

MakeFinding = Callable[..., Finding]

_HARDWARE = HardwareInfo(cpu="test-cpu", os="test-os")
_STARTED = datetime(2026, 1, 1, tzinfo=UTC)


def _truth(
    truth_id: str, path: str = "app.py", start_line: int = 10, cwe: int | None = 78
) -> GroundTruthFinding:
    return GroundTruthFinding(
        id=truth_id, location=SourceLocation(path=path, start_line=start_line), cwe=cwe
    )


def _run(dataset: Dataset, findings: list[Finding]) -> tuple[RunManifest, dict[str, bool]]:
    manifest, per_example = run_bench(
        dataset,
        findings,
        run_id="bench_test",
        git_sha="abc123",
        config_hash="cfg-hash",
        calibration_profile="static-default@1",
        started=_STARTED,
        wall_seconds=1.5,
        hardware=_HARDWARE,
    )
    return manifest, dict(per_example)


class TestRunBench:
    def test_a_detected_example_is_marked_true(self, make_finding: MakeFinding) -> None:
        dataset = Dataset(
            name="golden",
            version="v1",
            split="novel",
            examples=(DatasetExample(id="ex-1", path="ex-1.py", ground_truth=(_truth("gt-1"),)),),
        )
        finding = make_finding(finding_id="f1", path="app.py", start_line=10, cwe=78)
        manifest, per_example = _run(dataset, [finding])
        assert per_example == {"ex-1": True}
        assert manifest.metrics.recall == 1.0

    def test_an_undetected_example_is_marked_false(self) -> None:
        dataset = Dataset(
            name="golden",
            version="v1",
            split="novel",
            examples=(DatasetExample(id="ex-1", path="ex-1.py", ground_truth=(_truth("gt-1"),)),),
        )
        manifest, per_example = _run(dataset, [])
        assert per_example == {"ex-1": False}
        assert manifest.metrics.recall == 0.0

    def test_a_true_negative_example_has_no_detected_entry(self, make_finding: MakeFinding) -> None:
        dataset = Dataset(
            name="golden",
            version="v1",
            split="novel",
            examples=(
                DatasetExample(id="positive", path="a.py", ground_truth=(_truth("gt-1"),)),
                DatasetExample(id="negative", path="b.py", ground_truth=()),
            ),
        )
        finding = make_finding(finding_id="f1", path="app.py", start_line=10, cwe=78)
        _, per_example = _run(dataset, [finding])
        assert "negative" not in per_example
        assert "positive" in per_example

    def test_a_false_positive_on_a_true_negative_example_hurts_precision(
        self, make_finding: MakeFinding
    ) -> None:
        dataset = Dataset(
            name="golden",
            version="v1",
            split="novel",
            examples=(DatasetExample(id="negative", path="b.py", ground_truth=()),),
        )
        stray_finding = make_finding(finding_id="f1", path="unrelated.py", start_line=1, cwe=22)
        manifest, _ = _run(dataset, [stray_finding])
        assert manifest.metrics.precision == 0.0

    def test_manifest_carries_the_given_identifying_fields(self) -> None:
        dataset = Dataset(name="golden", version="v1", split="novel")
        manifest, _ = _run(dataset, [])
        assert manifest.run_id == "bench_test"
        assert manifest.git_sha == "abc123"
        assert manifest.config_hash == "cfg-hash"
        assert manifest.calibration_profile == "static-default@1"
        assert manifest.dataset.name == "golden"
        assert manifest.dataset.version == "v1"
        assert manifest.hardware == _HARDWARE

    def test_an_empty_dataset_yields_no_per_example_results(self) -> None:
        dataset = Dataset(name="golden", version="v1", split="novel")
        _, per_example = _run(dataset, [])
        assert per_example == {}

    def test_multiple_ground_truths_on_one_example_need_only_one_match(
        self, make_finding: MakeFinding
    ) -> None:
        dataset = Dataset(
            name="golden",
            version="v1",
            split="novel",
            examples=(
                DatasetExample(
                    id="ex-1",
                    path="ex-1.py",
                    ground_truth=(_truth("gt-1", start_line=10), _truth("gt-2", start_line=20)),
                ),
            ),
        )
        finding = make_finding(finding_id="f1", path="app.py", start_line=10, cwe=78)
        _, per_example = _run(dataset, [finding])
        assert per_example == {"ex-1": True}
