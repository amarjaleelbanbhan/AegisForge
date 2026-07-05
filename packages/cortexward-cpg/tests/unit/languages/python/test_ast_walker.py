"""Unit tests for the tree-sitter Python AST walker."""

from __future__ import annotations

import pytest
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder, InMemoryCodeGraph, NodeKind
from cortexward.languages.python._ast_walker import _location_for, walk_module

pytestmark = pytest.mark.unit

_PARSER = Parser(Language(tspython.language()))


def _parse(source: str) -> TSNode:
    return _PARSER.parse(source.encode("utf-8")).root_node


def _graph(source: str, file_path: str = "app.py") -> InMemoryCodeGraph:
    builder = GraphBuilder(language="python")
    walk_module(_parse(source), source=source.encode("utf-8"), file_path=file_path, builder=builder)
    return builder.build()


def _only(graph: InMemoryCodeGraph, kind: NodeKind) -> list[str]:
    return [node_id for node_id, node in graph.nodes.items() if node.kind is kind]


class TestNodeKinds:
    def test_module_is_module_kind(self) -> None:
        assert len(_only(_graph("x = 1\n"), NodeKind.MODULE)) == 1

    def test_function_and_class_kinds(self) -> None:
        graph = _graph("class Foo:\n    def bar(self):\n        pass\n")
        assert len(_only(graph, NodeKind.CLASS)) == 1
        assert len(_only(graph, NodeKind.FUNCTION)) == 1

    def test_parameters_are_marked(self) -> None:
        graph = _graph("def add(a, b):\n    return a\n")
        assert len(_only(graph, NodeKind.PARAMETER)) == 2

    def test_call_assignment_import_return(self) -> None:
        source = "import os\n\ndef f():\n    x = 1\n    os.getcwd()\n    return x\n"
        graph = _graph(source)
        assert _only(graph, NodeKind.IMPORT)
        assert _only(graph, NodeKind.ASSIGNMENT)
        assert _only(graph, NodeKind.CALL)
        assert _only(graph, NodeKind.RETURN)

    def test_branch_kinds(self) -> None:
        source = "def f(a):\n    if a:\n        pass\n    while a:\n        pass\n"
        assert len(_only(_graph(source), NodeKind.BRANCH)) == 2

    def test_literal_kinds(self) -> None:
        source = 'a = 1\nb = "s"\nc = True\nd = None\n'
        assert len(_only(_graph(source), NodeKind.LITERAL)) == 4

    def test_unmapped_construct_is_other(self) -> None:
        # A list literal has no dedicated kind; it must fall back to OTHER
        # rather than being silently dropped or mis-tagged.
        assert _only(_graph("x = [1, 2]\n"), NodeKind.OTHER)


class TestNames:
    def test_function_and_class_get_name_property(self) -> None:
        graph = _graph("class Foo:\n    def bar(self):\n        pass\n")
        names = {node.properties.get("name") for node in graph.nodes.values()}
        assert "Foo" in names
        assert "bar" in names


class TestAstChildEdges:
    def test_ast_child_edges_connect_module_to_function(self) -> None:
        graph = _graph("def f():\n    return 1\n")
        module_id = _only(graph, NodeKind.MODULE)[0]
        function_id = _only(graph, NodeKind.FUNCTION)[0]

        ast_children_of_module = {
            e.target for e in graph.edges if e.kind is EdgeKind.AST_CHILD and e.source == module_id
        }
        assert function_id in ast_children_of_module


class TestEntrypoints:
    def test_main_function_is_entrypoint(self) -> None:
        assert len(_graph("def main():\n    pass\n").entrypoints()) == 1

    def test_non_main_function_is_not_entrypoint(self) -> None:
        assert _graph("def handler():\n    pass\n").entrypoints() == ()

    def test_main_guard_is_entrypoint(self) -> None:
        source = 'def run():\n    pass\n\nif __name__ == "__main__":\n    run()\n'
        assert len(_graph(source).entrypoints()) == 1

    def test_unrelated_if_is_not_entrypoint(self) -> None:
        source = "def f(a):\n    if a > 0:\n        pass\n"
        assert _graph(source).entrypoints() == ()

    def test_main_function_and_guard_both_marked(self) -> None:
        source = 'def main():\n    pass\n\nif __name__ == "__main__":\n    main()\n'
        assert len(_graph(source).entrypoints()) == 2


class TestLocations:
    def test_location_line_numbers_are_one_indexed(self) -> None:
        graph = _graph("def f():\n    return 1\n")
        module_id = _only(graph, NodeKind.MODULE)[0]
        assert graph.location_of(module_id).start_line == 1

    def test_function_location_matches_source_line(self) -> None:
        source = "x = 1\n\n\ndef f():\n    return 1\n"
        graph = _graph(source)
        function_id = _only(graph, NodeKind.FUNCTION)[0]
        assert graph.location_of(function_id).start_line == 4


class TestNodeIdUniqueness:
    def test_wrapper_and_child_with_identical_byte_range_get_distinct_ids(self) -> None:
        # `expression_statement` wrapping a lone `call` spans the exact same
        # byte range as the call itself; the id scheme must not collide.
        graph = _graph("f()\n")
        assert len({*graph.nodes.keys()}) == len(graph.nodes)


class _FakeTSPoint:
    """A minimal stand-in for tree-sitter's (start_point, end_point) tuples."""

    def __init__(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self.start_point = start
        self.end_point = end


class TestLocationForDefendsAgainstInvertedSpans:
    def test_clamps_end_col_when_tree_sitter_reports_an_inverted_span(self) -> None:
        # tree-sitter is an external, evolving parser; _location_for must not
        # let a technically-inverted same-line span (end col < start col)
        # blow up SourceLocation's validation and crash the whole parse.
        fake_node = _FakeTSPoint(start=(0, 10), end=(0, 2))
        location = _location_for(fake_node, "app.py")  # type: ignore[arg-type]
        assert location.start_col == 11
        assert location.end_col == 11
