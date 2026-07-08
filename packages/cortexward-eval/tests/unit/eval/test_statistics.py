"""Unit tests for the statistical protocol: bootstrap CIs and McNemar's test."""

from __future__ import annotations

from statistics import fmean, median

import pytest

from cortexward.eval import bootstrap_ci, mcnemar_test
from cortexward.eval.statistics import _chi_square_cdf_df1

pytestmark = pytest.mark.unit


class TestBootstrapCi:
    def test_rejects_empty_samples(self) -> None:
        with pytest.raises(ValueError, match="at least one sample"):
            bootstrap_ci([])

    @pytest.mark.parametrize("confidence", [0.0, 1.0, -0.1, 1.5])
    def test_rejects_confidence_outside_open_unit_interval(self, confidence: float) -> None:
        with pytest.raises(ValueError, match="confidence must be"):
            bootstrap_ci([1.0, 2.0, 3.0], confidence=confidence)

    def test_point_estimate_is_the_statistic_over_the_original_samples(self) -> None:
        result = bootstrap_ci([1.0, 2.0, 3.0], seed=1, n_resamples=200)
        assert result.point_estimate == pytest.approx(fmean([1.0, 2.0, 3.0]))

    def test_constant_samples_yield_a_zero_width_interval(self) -> None:
        result = bootstrap_ci([5.0, 5.0, 5.0], seed=1, n_resamples=200)
        assert result.lower == result.upper == result.point_estimate == 5.0

    def test_lower_bound_never_exceeds_upper_bound(self) -> None:
        result = bootstrap_ci([1.0, 2.0, 10.0, 3.0, -5.0], seed=1, n_resamples=500)
        assert result.lower <= result.upper

    def test_same_seed_is_deterministic(self) -> None:
        samples = [1.0, 2.0, 3.0, 4.0, 5.0]
        first = bootstrap_ci(samples, seed=42, n_resamples=300)
        second = bootstrap_ci(samples, seed=42, n_resamples=300)
        assert first == second

    def test_different_seeds_can_disagree(self) -> None:
        samples = [1.0, 2.0, 3.0, 10.0, -5.0, 8.0]
        first = bootstrap_ci(samples, seed=1, n_resamples=200)
        second = bootstrap_ci(samples, seed=2, n_resamples=200)
        assert (first.lower, first.upper) != (second.lower, second.upper)

    def test_confidence_is_recorded_on_the_result(self) -> None:
        result = bootstrap_ci([1.0, 2.0, 3.0], confidence=0.9, seed=1, n_resamples=100)
        assert result.confidence == 0.9

    def test_a_wider_confidence_level_produces_a_wider_interval(self) -> None:
        samples = [1.0, 5.0, 2.0, 8.0, 3.0, 9.0, 4.0, 0.0]
        narrow = bootstrap_ci(samples, confidence=0.5, seed=7, n_resamples=2000)
        wide = bootstrap_ci(samples, confidence=0.99, seed=7, n_resamples=2000)
        assert (wide.upper - wide.lower) >= (narrow.upper - narrow.lower)

    def test_accepts_a_custom_statistic(self) -> None:
        result = bootstrap_ci([1.0, 2.0, 100.0], statistic=median, seed=1, n_resamples=200)
        assert result.point_estimate == 2.0

    def test_paired_delta_use_case_recovers_the_mean_difference(self) -> None:
        baseline = [0.5, 0.6, 0.4, 0.7]
        candidate = [0.6, 0.7, 0.5, 0.8]
        deltas = [c - b for b, c in zip(baseline, candidate, strict=True)]
        result = bootstrap_ci(deltas, seed=1, n_resamples=500)
        assert result.point_estimate == pytest.approx(0.1)


class TestChiSquareCdfDf1:
    def test_negative_input_is_zero(self) -> None:
        assert _chi_square_cdf_df1(-1.0) == 0.0

    def test_zero_input_is_zero(self) -> None:
        assert _chi_square_cdf_df1(0.0) == 0.0

    @pytest.mark.parametrize(
        ("critical_value", "expected_cdf"),
        [
            (3.8415, 0.95),  # the textbook df=1, alpha=0.05 critical value
            (6.6349, 0.99),  # alpha=0.01
            (10.8276, 0.999),  # alpha=0.001
        ],
    )
    def test_known_critical_values(self, critical_value: float, expected_cdf: float) -> None:
        assert _chi_square_cdf_df1(critical_value) == pytest.approx(expected_cdf, abs=1e-4)


class TestMcNemarTest:
    def test_rejects_negative_counts(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            mcnemar_test(-1, 5)

    def test_no_discordant_pairs_yields_p_value_of_one(self) -> None:
        result = mcnemar_test(0, 0)
        assert result.statistic == 0.0
        assert result.p_value == 1.0
        assert result.discordant_pairs == 0

    def test_is_symmetric_in_its_arguments(self) -> None:
        assert mcnemar_test(6, 16) == mcnemar_test(16, 6)

    def test_discordant_pairs_is_the_sum(self) -> None:
        result = mcnemar_test(6, 16)
        assert result.discordant_pairs == 22

    def test_matches_the_known_alpha_05_critical_value(self) -> None:
        # b=1, c=10 -> continuity-corrected statistic = (9-1)^2/11 = 5.818...
        # chosen so the statistic lands comfortably past the 3.8415 critical
        # value, giving p < 0.05.
        result = mcnemar_test(1, 10)
        assert result.statistic > 3.8415
        assert result.p_value < 0.05

    def test_balanced_discordant_counts_yield_a_high_p_value(self) -> None:
        result = mcnemar_test(10, 10)
        assert result.p_value > 0.5

    def test_more_imbalance_yields_a_smaller_p_value(self) -> None:
        balanced = mcnemar_test(10, 12)
        imbalanced = mcnemar_test(2, 20)
        assert imbalanced.p_value < balanced.p_value
