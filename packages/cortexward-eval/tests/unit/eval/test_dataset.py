"""Unit tests for `cortexward.eval.dataset`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cortexward.domain import SourceLocation
from cortexward.eval import Dataset, DatasetExample, GroundTruthFinding, load_dataset

pytestmark = pytest.mark.unit


def _example(
    example_id: str = "ex-1", *, ground_truth: tuple[GroundTruthFinding, ...] = ()
) -> DatasetExample:
    return DatasetExample(id=example_id, path=f"{example_id}.py", ground_truth=ground_truth)


class TestDatasetExample:
    def test_defaults_to_no_ground_truth(self) -> None:
        example = _example()
        assert example.ground_truth == ()

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DatasetExample(id="ex-1", path="ex-1.py", nonsense="x")  # type: ignore[call-arg]

    def test_carries_its_own_ground_truth(self) -> None:
        truth = GroundTruthFinding(
            id="gt-1", location=SourceLocation(path="ex-1.py", start_line=3), cwe=78
        )
        example = _example(ground_truth=(truth,))
        assert example.ground_truth == (truth,)


class TestDataset:
    def test_defaults_to_no_examples(self) -> None:
        dataset = Dataset(name="test", version="v1", split="novel")
        assert dataset.examples == ()

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            Dataset(name="test", version="v1", split="novel", nonsense="x")  # type: ignore[call-arg]

    def test_holds_its_examples_in_order(self) -> None:
        examples = (_example("a"), _example("b"))
        dataset = Dataset(name="test", version="v1", split="novel", examples=examples)
        assert dataset.examples == examples


class TestLoadDataset:
    def test_loads_a_valid_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            '{"name": "test", "version": "v1", "split": "novel", "examples": '
            '[{"id": "ex-1", "path": "ex-1.py", "ground_truth": []}]}',
            encoding="utf-8",
        )
        dataset = load_dataset(manifest_path)
        assert dataset.name == "test"
        assert dataset.version == "v1"
        assert dataset.split == "novel"
        assert len(dataset.examples) == 1
        assert dataset.examples[0].id == "ex-1"

    def test_rejects_a_malformed_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text('{"name": "test"}', encoding="utf-8")
        with pytest.raises(ValidationError):
            load_dataset(manifest_path)
