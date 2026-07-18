"""Unit tests for the deterministic finding-matcher and detection metrics."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cortexward.domain import Finding, SourceLocation
from cortexward.eval import (
    GroundTruthFinding,
    detection_metrics,
    f1_score,
    false_negative_rate,
    false_positive_rate,
    match_findings,
    precision,
    recall,
)

pytestmark = pytest.mark.unit

MakeFinding = Callable[..., Finding]


def _truth(
    truth_id: str = "truth-1", path: str = "app.py", start_line: int = 10, cwe: int | None = 89
) -> GroundTruthFinding:
    return GroundTruthFinding(
        id=truth_id, location=SourceLocation(path=path, start_line=start_line), cwe=cwe
    )


class TestMatchFindings:
    def test_a_matching_finding_and_truth_produce_a_true_positive(
        self, make_finding: MakeFinding
    ) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=10, cwe=89)
        result = match_findings([finding], [_truth()])
        assert result.true_positives == (("f1", "truth-1"),)
        assert result.false_positives == ()
        assert result.false_negatives == ()

    def test_an_unmatched_finding_is_a_false_positive(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="other.py", start_line=1)
        result = match_findings([finding], [_truth()])
        assert result.false_positives == ("f1",)
        assert result.true_positives == ()

    def test_an_unmatched_truth_is_a_false_negative(self, make_finding: MakeFinding) -> None:
        result = match_findings([], [_truth()])
        assert result.false_negatives == ("truth-1",)

    def test_different_cwe_does_not_match(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=10, cwe=79)
        result = match_findings([finding], [_truth(cwe=89)])
        assert result.false_positives == ("f1",)
        assert result.false_negatives == ("truth-1",)

    def test_truth_with_no_cwe_matches_any_finding_cwe(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=10, cwe=79)
        result = match_findings([finding], [_truth(cwe=None)])
        assert result.true_positives == (("f1", "truth-1"),)

    def test_different_file_path_does_not_match(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="other.py", start_line=10)
        result = match_findings([finding], [_truth(path="app.py")])
        assert result.false_positives == ("f1",)

    def test_backslash_and_forward_slash_paths_still_match(self, make_finding: MakeFinding) -> None:
        # A scanner emits OS-native paths (backslash-separated on Windows,
        # via str(Path(...))); a dataset's ground truth is authored once and
        # versioned in JSON, using the portable forward-slash convention
        # regardless of which OS a benchmark run executes on. Confirmed as a
        # real bug empirically: `ward bench run` matched nothing at all on
        # Windows before this normalization existed.
        finding = make_finding(finding_id="f1", path="examples\\app.py", start_line=10)
        result = match_findings([finding], [_truth(path="examples/app.py")])
        assert result.true_positives == (("f1", "truth-1"),)

    def test_overlapping_multiline_location_matches(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=8, end_line=12)
        result = match_findings([finding], [_truth(start_line=10)])
        assert result.true_positives == (("f1", "truth-1"),)

    def test_non_overlapping_lines_do_not_match(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=50)
        result = match_findings([finding], [_truth(start_line=10)])
        assert result.false_positives == ("f1",)

    def test_a_truth_item_is_only_matched_once(self, make_finding: MakeFinding) -> None:
        f1 = make_finding(finding_id="f1", path="app.py", start_line=10)
        f2 = make_finding(finding_id="f2", path="app.py", start_line=10)
        result = match_findings([f1, f2], [_truth()])
        assert result.true_positives == (("f1", "truth-1"),)
        assert result.false_positives == ("f2",)

    def test_empty_inputs_produce_no_matches(self) -> None:
        result = match_findings([], [])
        assert result == match_findings([], [])
        assert result.true_positives == ()
        assert result.false_positives == ()
        assert result.false_negatives == ()


class TestMetricFormulas:
    def test_perfect_match_yields_precision_recall_and_f1_of_one(
        self, make_finding: MakeFinding
    ) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=10)
        result = match_findings([finding], [_truth()])
        assert precision(result) == 1.0
        assert recall(result) == 1.0
        assert f1_score(result) == 1.0
        assert false_positive_rate(result) == 0.0
        assert false_negative_rate(result) == 0.0

    def test_all_false_positives_yields_zero_precision(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="other.py", start_line=1)
        result = match_findings([finding], [])
        assert precision(result) == 0.0
        assert false_positive_rate(result) == 1.0

    def test_all_false_negatives_yields_zero_recall(self) -> None:
        result = match_findings([], [_truth()])
        assert recall(result) == 0.0
        assert false_negative_rate(result) == 1.0

    def test_no_findings_and_no_truth_yields_zero_metrics_not_a_crash(self) -> None:
        result = match_findings([], [])
        assert precision(result) == 0.0
        assert recall(result) == 0.0
        assert f1_score(result) == 0.0
        assert false_positive_rate(result) == 0.0
        assert false_negative_rate(result) == 0.0

    def test_partial_match_computes_the_harmonic_mean(self, make_finding: MakeFinding) -> None:
        # 1 true positive, 1 false positive, 1 false negative:
        # precision = 1/2, recall = 1/2, f1 = 1/2.
        tp_finding = make_finding(finding_id="tp", path="app.py", start_line=10)
        fp_finding = make_finding(finding_id="fp", path="other.py", start_line=1)
        result = match_findings(
            [tp_finding, fp_finding],
            [_truth(truth_id="matched"), _truth(truth_id="missed", start_line=99)],
        )
        assert precision(result) == pytest.approx(0.5)
        assert recall(result) == pytest.approx(0.5)
        assert f1_score(result) == pytest.approx(0.5)


class TestDetectionMetricsBuilder:
    def test_produces_a_detection_metrics_block(self, make_finding: MakeFinding) -> None:
        finding = make_finding(finding_id="f1", path="app.py", start_line=10)
        result = match_findings([finding], [_truth()])
        metrics = detection_metrics(result)
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.f1 == 1.0
