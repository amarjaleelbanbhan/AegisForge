"""Detection-quality metrics (evaluation-framework.md §2.1, §6).

A **documented, deterministic matcher** is the whole point of this module:
without one, TP/FP/FN counts (and everything derived from them) aren't
reproducible across runs or comparable across tools. A predicted `Finding`
matches a `GroundTruthFinding` when:

1. Their CWEs are compatible — equal, or the ground-truth item carries no
   CWE at all (a permissive wildcard for labels that only pin down a
   location, not a specific weakness class).
2. At least one of the predicted finding's `locations` **overlaps** the
   ground truth's location — same file `path`, and their line ranges
   intersect (a single-line finding still counts as overlapping a
   multi-line ground-truth span, and vice versa).

Matching runs as **greedy bipartite matching in input order**: each
predicted finding claims the first still-unclaimed ground-truth item it
matches, and each ground-truth item can be claimed by at most one finding.
This is deliberately simple (not globally-optimal bipartite matching) —
input order is itself part of the documented contract, so results are
reproducible given the same predictions and ground truth in the same order,
which matters more here than shaving a percentage point off edge cases with
multiple equally-valid matchings.

**FPR/FNR convention.** There is no fixed universe of "negative" locations
in vulnerability detection (unlike classifying a fixed set of labeled
examples), so the classic `FP / (FP + TN)` definition doesn't apply. This
module instead reports:

- `fpr = FP / (FP + TP)` — the fraction of *reported* findings that are
  wrong (equivalently, `1 - precision`).
- `fnr = FN / (FN + TP)` — the fraction of *real* issues missed
  (equivalently, `1 - recall`).

This matches how FPR/FNR are commonly reported in vulnerability-detection
literature when no fixed negative set exists, and keeps every metric a
function of the same three counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from cortexward.domain import Finding, SourceLocation
from cortexward.eval.manifest import DetectionMetrics


class GroundTruthFinding(BaseModel):
    """One labeled example in a benchmark dataset (evaluation-framework.md §4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    location: SourceLocation
    cwe: int | None = Field(default=None, ge=1)


@dataclass(frozen=True)
class MatchResult:
    """The outcome of matching predicted findings against ground truth.

    `true_positives` pairs a matched finding's id with the ground-truth id
    it matched; `false_positives`/`false_negatives` are the unmatched ids
    on each side.
    """

    true_positives: tuple[tuple[str, str], ...]
    false_positives: tuple[str, ...]
    false_negatives: tuple[str, ...]


def _locations_overlap(a: SourceLocation, b: SourceLocation) -> bool:
    if a.path != b.path:
        return False
    a_end = a.end_line if a.end_line is not None else a.start_line
    b_end = b.end_line if b.end_line is not None else b.start_line
    return a.start_line <= b_end and b.start_line <= a_end


def _cwe_compatible(predicted_cwe: int | None, truth_cwe: int | None) -> bool:
    return truth_cwe is None or predicted_cwe == truth_cwe


def _is_match(finding: Finding, truth: GroundTruthFinding) -> bool:
    if not _cwe_compatible(finding.cwe, truth.cwe):
        return False
    return any(_locations_overlap(location, truth.location) for location in finding.locations)


def match_findings(
    findings: Sequence[Finding], ground_truth: Sequence[GroundTruthFinding]
) -> MatchResult:
    """Greedily matches `findings` against `ground_truth`; see the module docstring."""
    unmatched_truth = list(ground_truth)
    true_positives: list[tuple[str, str]] = []
    false_positives: list[str] = []
    for finding in findings:
        match_index = next(
            (index for index, truth in enumerate(unmatched_truth) if _is_match(finding, truth)),
            None,
        )
        if match_index is None:
            false_positives.append(finding.id)
        else:
            matched_truth = unmatched_truth.pop(match_index)
            true_positives.append((finding.id, matched_truth.id))
    false_negatives = [truth.id for truth in unmatched_truth]
    return MatchResult(
        true_positives=tuple(true_positives),
        false_positives=tuple(false_positives),
        false_negatives=tuple(false_negatives),
    )


def precision(match: MatchResult) -> float:
    tp, fp = len(match.true_positives), len(match.false_positives)
    return tp / (tp + fp) if (tp + fp) else 0.0


def recall(match: MatchResult) -> float:
    tp, fn = len(match.true_positives), len(match.false_negatives)
    return tp / (tp + fn) if (tp + fn) else 0.0


def f1_score(match: MatchResult) -> float:
    p, r = precision(match), recall(match)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def false_positive_rate(match: MatchResult) -> float:
    tp, fp = len(match.true_positives), len(match.false_positives)
    return fp / (fp + tp) if (fp + tp) else 0.0


def false_negative_rate(match: MatchResult) -> float:
    tp, fn = len(match.true_positives), len(match.false_negatives)
    return fn / (fn + tp) if (fn + tp) else 0.0


def detection_metrics(match: MatchResult) -> DetectionMetrics:
    """The full `DetectionMetrics` block for `match`, ready to embed in a `RunManifest`."""
    return DetectionMetrics(
        precision=precision(match),
        recall=recall(match),
        f1=f1_score(match),
        fpr=false_positive_rate(match),
        fnr=false_negative_rate(match),
    )
