"""The statistical protocol (evaluation-framework.md §6).

Two general, reusable primitives, kept deliberately independent of any
specific dataset or metric-aggregation shape (the golden dataset and its
contamination splits are still undecided — see ROADMAP.md — so nothing here
hardcodes how examples map onto a metric):

- **`bootstrap_ci`**: a percentile-bootstrap confidence interval for any
  statistic of a sequence of per-example values. "Detection deltas (F1):
  paired bootstrap confidence intervals over per-example results" (§6) means
  computing this over the per-example paired differences
  (`[candidate[i] - baseline[i] for i in ...]`) with `statistic=mean` — the
  caller supplies that sequence; this function doesn't assume how it was
  derived.
- **`mcnemar_test`**: McNemar's chi-square test (with continuity correction)
  for matched binary outcomes — "detected / not" pairs from two
  configurations evaluated on the same examples.

No `scipy` dependency: the chi-square(1) CDF McNemar's test needs has an
exact closed form (a chi-square(1) variable is the square of a standard
normal), so it's computed directly via `math.erf`.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True)
class ConfidenceInterval:
    """A point estimate plus its bootstrap confidence interval."""

    point_estimate: float
    lower: float
    upper: float
    confidence: float


def bootstrap_ci(
    samples: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float] = fmean,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int | None = None,
) -> ConfidenceInterval:
    """A percentile-bootstrap confidence interval for `statistic(samples)`.

    Resamples `samples` with replacement `n_resamples` times, recomputes
    `statistic` on each resample, and reports the `confidence`-level
    percentile interval of the resampled statistics. `seed` makes the
    resampling deterministic — reproducibility of a reported CI matters as
    much as the CI itself (evaluation-framework.md §8: everything a reviewer
    needs to re-run is versioned and documented).
    """
    if not samples:
        raise ValueError("bootstrap_ci requires at least one sample")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be strictly between 0 and 1")
    # Statistical resampling, not cryptographic.
    rng = random.Random(seed)  # noqa: S311 # nosec B311
    n = len(samples)
    resampled_statistics = [
        statistic([samples[rng.randrange(n)] for _ in range(n)]) for _ in range(n_resamples)
    ]
    resampled_statistics.sort()
    alpha = 1 - confidence
    lower_index = _clamp(round((alpha / 2) * n_resamples), n_resamples)
    upper_index = _clamp(round((1 - alpha / 2) * n_resamples) - 1, n_resamples)
    return ConfidenceInterval(
        point_estimate=statistic(samples),
        lower=resampled_statistics[lower_index],
        upper=resampled_statistics[upper_index],
        confidence=confidence,
    )


def _clamp(index: int, n_resamples: int) -> int:
    return max(0, min(index, n_resamples - 1))


@dataclass(frozen=True)
class McNemarResult:
    """The outcome of McNemar's test on one pair of configurations."""

    statistic: float
    p_value: float
    discordant_pairs: int


def mcnemar_test(only_a_detected: int, only_b_detected: int) -> McNemarResult:
    """McNemar's chi-square test (continuity-corrected) for matched binary outcomes.

    `only_a_detected`/`only_b_detected` are the *discordant*-pair counts
    from a 2x2 contingency table over the same examples evaluated by two
    configurations A and B: examples A detected but B didn't, and vice
    versa. Concordant pairs (both detected, both missed) carry no
    information for this test and aren't inputs here.

    Uses the classic Edwards' continuity-corrected statistic
    (`(|b - c| - 1)^2 / (b + c)`, df=1). The exact binomial variant
    recommended for small discordant counts (commonly < 25) is out of
    scope — documented, not silently treated as equivalent.
    """
    if only_a_detected < 0 or only_b_detected < 0:
        raise ValueError("discordant pair counts must be non-negative")
    discordant = only_a_detected + only_b_detected
    if discordant == 0:
        return McNemarResult(statistic=0.0, p_value=1.0, discordant_pairs=0)
    statistic = (abs(only_a_detected - only_b_detected) - 1) ** 2 / discordant
    return McNemarResult(
        statistic=statistic,
        p_value=1.0 - _chi_square_cdf_df1(statistic),
        discordant_pairs=discordant,
    )


def _chi_square_cdf_df1(x: float) -> float:
    """The chi-square(1) CDF: `P(X <= x) = erf(sqrt(x / 2))` for `x >= 0`.

    Exact closed form (a chi-square(1) variable is the square of a standard
    normal) — no numeric integration or `scipy` dependency needed for this
    one special case.
    """
    if x < 0:
        return 0.0
    return math.erf(math.sqrt(x / 2))
