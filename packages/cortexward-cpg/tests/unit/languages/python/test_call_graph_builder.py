"""Unit tests for the call-graph (CALLS) builder.

CALLS edges connect a `call` node to the function/method definition(s) it
resolves to, via best-effort same-file name resolution (see the module
docstring in `_call_graph_builder` for the exact rules and scope limits).
"""

from __future__ import annotations

import pytest
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder, InMemoryCodeGraph, NodeKind
from cortexward.domain import SourceLocation
from cortexward.languages.python._ast_walker import ts_node_key, walk_module
from cortexward.languages.python._call_graph_builder import (
    _collect_definitions,
    _resolve_callee,
    _resolve_calls,
    build_call_graph,
)

pytestmark = pytest.mark.unit

_PARSER = Parser(Language(tspython.language()))


def _parse(source: str) -> TSNode:
    return _PARSER.parse(source.encode("utf-8")).root_node


def _graph(source: str, file_path: str = "app.py") -> InMemoryCodeGraph:
    builder = GraphBuilder(language="python")
    root = _parse(source)
    encoded = source.encode("utf-8")
    result = walk_module(root, source=encoded, file_path=file_path, builder=builder)
    build_call_graph(root, node_ids=result.node_ids, source=encoded, builder=builder)
    return builder.build()


def _calls_edges(graph: InMemoryCodeGraph) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in graph.edges if e.kind is EdgeKind.CALLS}


def _function_named(graph: InMemoryCodeGraph, name: str) -> str:
    matches = [
        node_id
        for node_id, node in graph.nodes.items()
        if node.kind is NodeKind.FUNCTION and node.properties.get("name") == name
    ]
    assert len(matches) == 1, f"expected exactly one function named {name!r}, found {len(matches)}"
    return matches[0]


def _call_at_line(graph: InMemoryCodeGraph, line: int) -> str:
    matches = [
        node_id
        for node_id, node in graph.nodes.items()
        if node.kind is NodeKind.CALL and graph.location_of(node_id).start_line == line
    ]
    assert len(matches) == 1, f"expected exactly one call on line {line}, found {len(matches)}"
    return matches[0]


class TestPlainFunctionCalls:
    def test_bare_call_resolves_to_the_matching_function(self) -> None:
        source = "def helper():\n    pass\n\ndef main():\n    helper()\n"
        graph = _graph(source)
        call_id = _call_at_line(graph, 5)
        helper_id = _function_named(graph, "helper")
        edges = _calls_edges(graph)
        assert (call_id, helper_id) in edges

    def test_call_before_its_definition_still_resolves(self) -> None:
        # Definitions are collected before calls are resolved, so forward
        # references (calling a function defined later) work too.
        source = "def main():\n    helper()\n\ndef helper():\n    pass\n"
        graph = _graph(source)
        call_id = _call_at_line(graph, 2)
        helper_id = _function_named(graph, "helper")
        edges = _calls_edges(graph)
        assert (call_id, helper_id) in edges

    def test_unresolvable_call_gets_no_edge(self) -> None:
        # `print` has no matching in-file definition — no crash, just no edge.
        source = "def main():\n    print('hi')\n"
        graph = _graph(source)
        call_id = _call_at_line(graph, 2)
        edges = _calls_edges(graph)
        assert not any(s == call_id for s, _t in edges)

    def test_call_with_a_complex_callee_gets_no_edge(self) -> None:
        # `foo()()` — the outer call's callee is itself a `call`, not an
        # identifier or attribute; not resolvable by name, no crash. Both
        # calls share the same start position, so they're told apart by
        # span length (the outer call's is longer).
        source = "def foo():\n    pass\n\ndef main():\n    foo()()\n"
        graph = _graph(source)
        calls_on_line_5 = sorted(
            (
                node_id
                for node_id, node in graph.nodes.items()
                if node.kind is NodeKind.CALL and graph.location_of(node_id).start_line == 5
            ),
            key=lambda n: graph.location_of(n).end_col or 0,
        )
        assert len(calls_on_line_5) == 2
        inner_call_id, outer_call_id = calls_on_line_5
        foo_id = _function_named(graph, "foo")
        edges = _calls_edges(graph)
        assert (inner_call_id, foo_id) in edges
        assert (outer_call_id, foo_id) not in edges
        assert not any(s == outer_call_id for s, _t in edges)


class TestMethodCalls:
    def test_self_dot_method_call_resolves_to_the_method(self) -> None:
        source = (
            "class Foo:\n    def bar(self):\n        self.baz()\n    def baz(self):\n        pass\n"
        )
        graph = _graph(source)
        call_id = _call_at_line(graph, 3)
        baz_id = _function_named(graph, "baz")
        edges = _calls_edges(graph)
        assert (call_id, baz_id) in edges

    def test_method_call_does_not_resolve_against_plain_functions(self) -> None:
        # A module-level function and a method share a name; `self.run()`
        # must only resolve to the method, not the unrelated plain function.
        source = (
            "def run():\n"
            "    pass\n\n"
            "class Foo:\n"
            "    def run(self):\n"
            "        pass\n"
            "    def start(self):\n"
            "        self.run()\n"
        )
        graph = _graph(source)
        call_id = _call_at_line(graph, 8)
        plain_run_ids = [
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.FUNCTION
            and node.properties.get("name") == "run"
            and graph.location_of(node_id).start_line == 1
        ]
        method_run_ids = [
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.FUNCTION
            and node.properties.get("name") == "run"
            and graph.location_of(node_id).start_line == 5
        ]
        assert len(plain_run_ids) == 1
        assert len(method_run_ids) == 1
        edges = _calls_edges(graph)
        assert (call_id, method_run_ids[0]) in edges
        assert (call_id, plain_run_ids[0]) not in edges


class TestNestedFunctions:
    def test_function_nested_inside_a_method_is_not_itself_a_method(self) -> None:
        # A closure defined inside a method's body is a plain function for
        # resolution purposes, resolvable via a bare identifier call, not
        # `self.<name>()`.
        source = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        def inner():\n"
            "            pass\n"
            "        inner()\n"
        )
        graph = _graph(source)
        call_id = _call_at_line(graph, 5)
        inner_id = _function_named(graph, "inner")
        edges = _calls_edges(graph)
        assert (call_id, inner_id) in edges


class TestAmbiguousResolution:
    def test_same_named_functions_in_different_scopes_both_get_edges(self) -> None:
        source = (
            "def helper():\n"
            "    pass\n\n"
            "def other():\n"
            "    def helper():\n"
            "        pass\n"
            "    helper()\n\n"
            "def main():\n"
            "    helper()\n"
        )
        graph = _graph(source)
        outer_call = _call_at_line(graph, 10)
        outer_helper = next(
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.FUNCTION
            and node.properties.get("name") == "helper"
            and graph.location_of(node_id).start_line == 1
        )
        inner_helper = next(
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.FUNCTION
            and node.properties.get("name") == "helper"
            and graph.location_of(node_id).start_line == 5
        )
        edges = _calls_edges(graph)
        # The call inside `main` is name-resolved conservatively against
        # every same-named plain function in the file, including one nested
        # in an unrelated function — a documented over-approximation.
        assert (outer_call, outer_helper) in edges
        assert (outer_call, inner_helper) in edges


class TestCallerQuery:
    def test_graph_callers_reflects_the_calls_edge(self) -> None:
        source = "def helper():\n    pass\n\ndef main():\n    helper()\n"
        graph = _graph(source)
        call_id = _call_at_line(graph, 5)
        helper_id = _function_named(graph, "helper")
        assert graph.callers(helper_id) == (call_id,)


class _FakeNode:
    """A minimal stand-in for tree-sitter's `Node` (see
    `test_dfg_builder._FakeNode` for the same pattern and rationale).
    """

    def __init__(
        self,
        node_type: str,
        *,
        named_children: tuple[object, ...] = (),
        fields: dict[str, object] | None = None,
        start_byte: int = 0,
        end_byte: int = 0,
    ) -> None:
        self.type = node_type
        self.named_children = list(named_children)
        self._fields = fields or {}
        self.start_byte = start_byte
        self.end_byte = end_byte

    def child_by_field_name(self, name: str) -> object | None:
        return self._fields.get(name)


class TestMalformedTreeDefenses:
    """Direct tests of internal guards against incomplete/malformed parse
    trees (see `test_cfg_builder.TestMalformedTreeDefenses` for the same
    rationale): tree-sitter is error-tolerant and can produce trees a
    syntactically valid Python grammar would never contain.
    """

    def test_collect_definitions_tolerates_a_function_with_no_name_field(self) -> None:
        plain: dict[str, list[str]] = {}
        methods: dict[str, list[str]] = {}
        _collect_definitions(
            _FakeNode("function_definition"),  # type: ignore[arg-type]
            node_ids={},
            source=b"",
            in_class=False,
            plain=plain,
            methods=methods,
        )
        assert plain == {}
        assert methods == {}

    def test_collect_definitions_tolerates_a_class_with_no_body_field(self) -> None:
        plain: dict[str, list[str]] = {}
        methods: dict[str, list[str]] = {}
        _collect_definitions(
            _FakeNode("class_definition"),  # type: ignore[arg-type]
            node_ids={},
            source=b"",
            in_class=False,
            plain=plain,
            methods=methods,
        )
        assert plain == {}
        assert methods == {}

    def test_resolve_callee_tolerates_an_attribute_with_no_attribute_field(self) -> None:
        result = _resolve_callee(
            _FakeNode("attribute"),  # type: ignore[arg-type]
            source=b"",
            plain={},
            methods={"whatever": ["n1"]},
        )
        assert result == []

    def test_resolve_calls_tolerates_a_call_with_no_function_field(self) -> None:
        fake_call = _FakeNode("call", start_byte=0, end_byte=1)
        node_ids = {ts_node_key(fake_call): "n-call"}  # type: ignore[arg-type]
        builder = GraphBuilder(language="python")
        builder.add_node("n-call", NodeKind.CALL, _location())
        _resolve_calls(
            fake_call,  # type: ignore[arg-type]
            node_ids=node_ids,
            source=b"",
            plain={},
            methods={},
            builder=builder,
        )
        assert builder.build().edges == ()


def _location() -> SourceLocation:
    return SourceLocation(path="app.py", start_line=1, start_col=1, end_line=1, end_col=1)
