"""Conformance test for the LanguageProvider port."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from cortexward.domain import SourceLocation
from cortexward.ports import CodeGraph, LanguageProvider, NodeId, TaintPath

pytestmark = pytest.mark.unit


class _EmptyGraph:
    language = "python"

    def entrypoints(self) -> Sequence[NodeId]:
        return ()

    def reachable(self, sources: Sequence[NodeId], sink: NodeId) -> bool:
        return False

    def taint(
        self,
        sources: Sequence[NodeId],
        sinks: Sequence[NodeId],
        sanitizers: Sequence[NodeId] = (),
    ) -> Sequence[TaintPath]:
        return ()

    def callers(self, function: NodeId) -> Sequence[NodeId]:
        return ()

    def slice(self, node: NodeId) -> Sequence[NodeId]:
        return ()

    def location_of(self, node: NodeId) -> SourceLocation:
        return SourceLocation(path="unknown", start_line=1)

    def nodes_at(self, path: str, line: int) -> Sequence[NodeId]:
        return ()


class _FakePythonProvider:
    language = "python"

    def detect(self, root: Path) -> bool:
        return (root / "pyproject.toml").exists() or any(root.glob("*.py"))

    def parse(self, root: Path) -> CodeGraph:
        return _EmptyGraph()

    def dependency_manifests(self, root: Path) -> Sequence[Path]:
        candidates = (root / "pyproject.toml", root / "requirements.txt")
        return tuple(p for p in candidates if p.exists())


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(_FakePythonProvider(), LanguageProvider)


def test_detect_and_parse(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    provider = _FakePythonProvider()
    assert provider.detect(tmp_path) is True
    graph = provider.parse(tmp_path)
    assert isinstance(graph, CodeGraph)
    assert provider.dependency_manifests(tmp_path) == (tmp_path / "pyproject.toml",)


def test_detect_false_for_unrelated_tree(tmp_path: Path) -> None:
    assert _FakePythonProvider().detect(tmp_path) is False
