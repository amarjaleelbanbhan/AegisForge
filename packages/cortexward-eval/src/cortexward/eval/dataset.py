"""A versioned, labeled dataset (evaluation-framework.md §4).

`Dataset`/`DatasetExample` are the harness's own dataset shape: a name,
version, contamination `split` (evaluation-framework.md §4.2), and a set of
labeled examples, each a source file plus its ground-truth findings. This
module only loads and validates a dataset manifest — it never reads or
executes the example source files themselves; that stays the caller's job
(`ward bench run`, `cortexward-cli`), keeping this package free of any
scanner/filesystem-scanning dependency (the "evaluation harness does not
depend on other adapters" import-linter contract).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cortexward.eval.metrics import GroundTruthFinding


class DatasetExample(BaseModel):
    """One labeled example: a source file plus its ground-truth findings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    path: str = Field(
        min_length=1, description="Path to the example file, relative to the dataset root."
    )
    ground_truth: tuple[GroundTruthFinding, ...] = Field(default_factory=tuple)
    """Empty for a true-negative example: deliberately vulnerability-free,
    included so precision is measured against real code, not only recall
    against known-positive examples."""


class Dataset(BaseModel):
    """A versioned suite of labeled examples (evaluation-framework.md §4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    split: str = Field(
        min_length=1,
        description=(
            'Contamination split (§4.2): "memorized" / "post_cutoff" / "mutated" / "novel".'
        ),
    )
    examples: tuple[DatasetExample, ...] = Field(default_factory=tuple)


def load_dataset(manifest_path: Path) -> Dataset:
    """Loads and validates a dataset manifest from `manifest_path`."""
    return Dataset.model_validate_json(manifest_path.read_text(encoding="utf-8"))


__all__ = ["Dataset", "DatasetExample", "load_dataset"]
