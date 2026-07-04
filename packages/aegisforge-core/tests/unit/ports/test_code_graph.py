"""Conformance test for the CodeGraph port.

Exercises a minimal in-memory implementation to prove the protocol is
satisfiable and its query methods compose as intended.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from aegisforge.domain import SourceLocation
from aegisforge.ports import CodeGraph, NodeId, TaintPath

pytestmark = pytest.mark.unit


class _FakeGraph:
    """A tiny two-node graph: a source flowing into a sink with no sanitizer."""

    language = "python"

    def entrypoints(self) -> Sequence[NodeId]:
        return ("fn:handler",)

    def reachable(self, sources: Sequence[NodeId], sink: NodeId) -> bool:
        return sink == "call:execute" and "fn:handler" in sources

    def taint(
        self,
        sources: Sequence[NodeId],
        sinks: Sequence[NodeId],
        sanitizers: Sequence[NodeId] = (),
    ) -> Sequence[TaintPath]:
        if "param:query" in sources and "call:execute" in sinks:
            return (
                TaintPath(
                    source="param:query",
                    sink="call:execute",
                    path=("param:query", "var:sql", "call:execute"),
                    sanitized="var:sql" in sanitizers,
                ),
            )
        return ()

    def callers(self, function: NodeId) -> Sequence[NodeId]:
        return ("fn:handler",) if function == "fn:build_query" else ()

    def slice(self, node: NodeId) -> Sequence[NodeId]:
        return ("param:query", node)

    def location_of(self, node: NodeId) -> SourceLocation:
        return SourceLocation(path="app/db.py", start_line=1)


def test_fake_graph_satisfies_protocol() -> None:
    assert isinstance(_FakeGraph(), CodeGraph)


def test_taint_reports_unsanitized_flow() -> None:
    graph = _FakeGraph()
    paths = graph.taint(sources=("param:query",), sinks=("call:execute",))
    assert len(paths) == 1
    assert paths[0].sanitized is False
    assert paths[0].source == "param:query"


def test_taint_marks_sanitized_flow() -> None:
    graph = _FakeGraph()
    paths = graph.taint(sources=("param:query",), sinks=("call:execute",), sanitizers=("var:sql",))
    assert paths[0].sanitized is True


def test_reachable_and_location() -> None:
    graph = _FakeGraph()
    assert graph.reachable(sources=graph.entrypoints(), sink="call:execute")
    loc = graph.location_of("call:execute")
    assert loc.path == "app/db.py"
