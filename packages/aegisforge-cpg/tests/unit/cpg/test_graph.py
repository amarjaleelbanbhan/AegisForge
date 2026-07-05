"""Unit tests for GraphBuilder and InMemoryCodeGraph.

Builds a small synthetic graph modeling a classic SQL-injection shape:
``handler`` calls ``build_query``, whose ``query`` parameter is tainted
data flowing into an ``execute`` call. A separate, disconnected
``unrelated`` function exercises the "no path found" cases, and a
self-referential edge exercises cycle safety.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from aegisforge.cpg import EdgeKind, GraphBuilder, InMemoryCodeGraph, NodeKind
from aegisforge.domain import SourceLocation
from aegisforge.ports import CodeGraph

pytestmark = pytest.mark.unit

MakeLocation = Callable[..., SourceLocation]


@pytest.fixture
def sql_injection_graph(make_location: MakeLocation) -> InMemoryCodeGraph:
    builder = GraphBuilder(language="python")
    builder.add_node("fn:handler", NodeKind.FUNCTION, make_location(1))
    builder.add_node("param:query", NodeKind.PARAMETER, make_location(2))
    builder.add_node("call:build_query", NodeKind.CALL, make_location(3))
    builder.add_node("fn:build_query", NodeKind.FUNCTION, make_location(10))
    builder.add_node("var:sql", NodeKind.ASSIGNMENT, make_location(11))
    builder.add_node("call:execute", NodeKind.CALL, make_location(12))
    builder.add_node("fn:unrelated", NodeKind.FUNCTION, make_location(20))

    builder.add_edge(EdgeKind.CFG_NEXT, "fn:handler", "call:build_query")
    builder.add_edge(EdgeKind.CALLS, "call:build_query", "fn:build_query")
    builder.add_edge(EdgeKind.CFG_NEXT, "fn:build_query", "var:sql")
    builder.add_edge(EdgeKind.CFG_NEXT, "var:sql", "call:execute")
    builder.add_edge(EdgeKind.DFG_REACHES, "param:query", "var:sql")
    builder.add_edge(EdgeKind.DFG_REACHES, "var:sql", "call:execute")

    builder.mark_entrypoint("fn:handler")
    return builder.build()


class TestGraphBuilder:
    def test_add_node_returns_id(self, make_location: MakeLocation) -> None:
        builder = GraphBuilder(language="python")
        assert builder.add_node("fn:a", NodeKind.FUNCTION, make_location()) == "fn:a"

    def test_add_node_rejects_duplicate(self, make_location: MakeLocation) -> None:
        builder = GraphBuilder(language="python")
        builder.add_node("fn:a", NodeKind.FUNCTION, make_location())
        with pytest.raises(ValueError, match="already added"):
            builder.add_node("fn:a", NodeKind.FUNCTION, make_location())

    def test_add_edge_rejects_unknown_endpoint(self, make_location: MakeLocation) -> None:
        builder = GraphBuilder(language="python")
        builder.add_node("fn:a", NodeKind.FUNCTION, make_location())
        with pytest.raises(ValueError, match="unknown node"):
            builder.add_edge(EdgeKind.CALLS, "fn:a", "fn:missing")

    def test_mark_entrypoint_rejects_unknown_node(self) -> None:
        builder = GraphBuilder(language="python")
        with pytest.raises(ValueError, match="unknown node"):
            builder.mark_entrypoint("fn:missing")

    def test_build_produces_code_graph(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert isinstance(sql_injection_graph, CodeGraph)
        assert sql_injection_graph.language == "python"


class TestReachable:
    def test_reachable_across_a_call(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert sql_injection_graph.reachable(["fn:handler"], "call:execute") is True

    def test_unreachable_to_unrelated_function(
        self, sql_injection_graph: InMemoryCodeGraph
    ) -> None:
        assert sql_injection_graph.reachable(["fn:handler"], "fn:unrelated") is False

    def test_source_equal_to_sink_is_reachable(
        self, sql_injection_graph: InMemoryCodeGraph
    ) -> None:
        assert sql_injection_graph.reachable(["fn:handler"], "fn:handler") is True

    def test_unknown_node_raises_key_error(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        with pytest.raises(KeyError):
            sql_injection_graph.reachable(["fn:handler"], "fn:does-not-exist")


class TestTaint:
    def test_unsanitized_flow_is_reported(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        paths = sql_injection_graph.taint(sources=["param:query"], sinks=["call:execute"])
        assert len(paths) == 1
        assert paths[0].source == "param:query"
        assert paths[0].sink == "call:execute"
        assert paths[0].path == ("param:query", "var:sql", "call:execute")
        assert paths[0].sanitized is False

    def test_sanitizer_on_path_is_marked(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        paths = sql_injection_graph.taint(
            sources=["param:query"], sinks=["call:execute"], sanitizers=["var:sql"]
        )
        assert paths[0].sanitized is True

    def test_no_data_flow_edges_yields_no_paths(
        self, sql_injection_graph: InMemoryCodeGraph
    ) -> None:
        # fn:handler has no outgoing DFG_REACHES edges at all.
        assert sql_injection_graph.taint(sources=["fn:handler"], sinks=["call:execute"]) == ()

    def test_disconnected_source_yields_no_paths(
        self, sql_injection_graph: InMemoryCodeGraph
    ) -> None:
        assert sql_injection_graph.taint(sources=["param:query"], sinks=["fn:unrelated"]) == ()

    def test_multiple_sources_each_reporting(self, make_location: MakeLocation) -> None:
        builder = GraphBuilder(language="python")
        builder.add_node("src:a", NodeKind.IDENTIFIER, make_location())
        builder.add_node("src:b", NodeKind.IDENTIFIER, make_location())
        builder.add_node("sink:x", NodeKind.CALL, make_location())
        builder.add_edge(EdgeKind.DFG_REACHES, "src:a", "sink:x")
        builder.add_edge(EdgeKind.DFG_REACHES, "src:b", "sink:x")
        graph = builder.build()

        paths = graph.taint(sources=["src:a", "src:b"], sinks=["sink:x"])
        assert {p.source for p in paths} == {"src:a", "src:b"}

    def test_source_that_is_itself_a_sink_is_a_trivial_path(
        self, sql_injection_graph: InMemoryCodeGraph
    ) -> None:
        # A node that is simultaneously listed as a source and a sink is
        # trivially "tainted" by itself, with a single-element path.
        paths = sql_injection_graph.taint(sources=["var:sql"], sinks=["var:sql", "call:execute"])
        by_sink = {p.sink: p for p in paths}
        assert by_sink["var:sql"].path == ("var:sql",)
        assert by_sink["call:execute"].path == ("var:sql", "call:execute")


class TestCallers:
    def test_direct_callers(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert sql_injection_graph.callers("fn:build_query") == ("call:build_query",)

    def test_no_callers_is_empty(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert sql_injection_graph.callers("fn:unrelated") == ()


class TestSlice:
    def test_slice_includes_self_and_influencers(
        self, sql_injection_graph: InMemoryCodeGraph
    ) -> None:
        result = set(sql_injection_graph.slice("call:execute"))
        assert "call:execute" in result
        assert "var:sql" in result
        assert "param:query" in result
        assert "fn:unrelated" not in result

    def test_slice_of_isolated_node_is_itself(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert sql_injection_graph.slice("fn:unrelated") == ("fn:unrelated",)


class TestLocationOf:
    def test_returns_recorded_location(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert sql_injection_graph.location_of("fn:handler").start_line == 1

    def test_unknown_node_raises_key_error(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        with pytest.raises(KeyError):
            sql_injection_graph.location_of("fn:does-not-exist")


class TestEntrypoints:
    def test_returns_marked_entrypoints(self, sql_injection_graph: InMemoryCodeGraph) -> None:
        assert sql_injection_graph.entrypoints() == ("fn:handler",)


class TestCycleSafety:
    def test_reachable_terminates_with_a_cycle(self, make_location: MakeLocation) -> None:
        builder = GraphBuilder(language="python")
        builder.add_node("a", NodeKind.FUNCTION, make_location())
        builder.add_node("b", NodeKind.FUNCTION, make_location())
        builder.add_edge(EdgeKind.CFG_NEXT, "a", "b")
        builder.add_edge(EdgeKind.CFG_NEXT, "b", "a")
        graph = builder.build()

        assert graph.reachable(["a"], "b") is True
        assert graph.reachable(["b"], "a") is True

    def test_taint_terminates_with_a_cycle(self, make_location: MakeLocation) -> None:
        builder = GraphBuilder(language="python")
        builder.add_node("a", NodeKind.IDENTIFIER, make_location())
        builder.add_node("b", NodeKind.IDENTIFIER, make_location())
        builder.add_node("sink", NodeKind.CALL, make_location())
        builder.add_edge(EdgeKind.DFG_REACHES, "a", "b")
        builder.add_edge(EdgeKind.DFG_REACHES, "b", "a")
        graph = builder.build()

        # No edge into "sink" exists; the cycle between a/b must not hang the search.
        assert graph.taint(sources=["a"], sinks=["sink"]) == ()

    def test_reachable_diamond_revisits_a_node_without_reprocessing(
        self, make_location: MakeLocation
    ) -> None:
        # entry -> b -> d -> sink
        # entry -> c -> d           (d is reached twice; the second visit
        #                            must be skipped, not re-queued)
        builder = GraphBuilder(language="python")
        for node_id in ("entry", "b", "c", "d", "sink"):
            builder.add_node(node_id, NodeKind.FUNCTION, make_location())
        builder.add_edge(EdgeKind.CFG_NEXT, "entry", "b")
        builder.add_edge(EdgeKind.CFG_NEXT, "entry", "c")
        builder.add_edge(EdgeKind.CFG_NEXT, "b", "d")
        builder.add_edge(EdgeKind.CFG_NEXT, "c", "d")
        builder.add_edge(EdgeKind.CFG_NEXT, "d", "sink")
        graph = builder.build()

        assert graph.reachable(["entry"], "sink") is True
