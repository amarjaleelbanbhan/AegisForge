"""Unit tests for the data-flow (DFG_REACHES) builder.

Uses real reaching-definitions dataflow analysis over the CFG built by
`_cfg_builder`. DFG_REACHES edges connect a defining identifier node to a
using identifier node when the definition can reach that use via some CFG
path without an intervening redefinition of the same name.
"""

from __future__ import annotations

import pytest
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder, InMemoryCodeGraph, NodeKind
from cortexward.languages.python._ast_walker import ts_node_key, walk_module
from cortexward.languages.python._cfg_builder import build_control_flow
from cortexward.languages.python._dfg_builder import (
    _collect_uses,
    _DataFlowCollector,
    _extract_augmented_assignment,
    _extract_defs_uses,
    _extract_plain_assignment,
    _parameter_defs,
    build_data_flow,
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
    cfg_edges = build_control_flow(root, node_ids=result.node_ids, builder=builder)
    build_data_flow(
        root, node_ids=result.node_ids, cfg_edges=cfg_edges, source=encoded, builder=builder
    )
    return builder.build()


def _dfg_edges(graph: InMemoryCodeGraph) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in graph.edges if e.kind is EdgeKind.DFG_REACHES}


def _identifier_at_line(graph: InMemoryCodeGraph, line: int, occurrence: int = 0) -> str:
    """The `occurrence`-th (0-indexed) identifier node whose span starts on `line`."""
    matches = sorted(
        (
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.IDENTIFIER and graph.location_of(node_id).start_line == line
        ),
        key=lambda n: graph.location_of(n).start_col,
    )
    return matches[occurrence]


def _parameter_at_line(graph: InMemoryCodeGraph, line: int, occurrence: int = 0) -> str:
    """The `occurrence`-th (0-indexed) PARAMETER-kind node whose span starts on `line`.

    Parameter names are classified as `NodeKind.PARAMETER` (not IDENTIFIER) by
    the AST walker, since they sit directly under a `parameters` node.
    """
    matches = sorted(
        (
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.PARAMETER and graph.location_of(node_id).start_line == line
        ),
        key=lambda n: graph.location_of(n).start_col,
    )
    return matches[occurrence]


class TestSimpleAssignment:
    def test_definition_reaches_a_later_use(self) -> None:
        source = "x = 1\ny = x\n"
        graph = _graph(source)
        def_id = _identifier_at_line(graph, 1)  # x on the left of `x = 1`
        use_id = _identifier_at_line(graph, 2, occurrence=1)  # x on the right of `y = x`
        edges = _dfg_edges(graph)
        assert (def_id, use_id) in edges

    def test_no_edge_before_the_definition(self) -> None:
        source = "print(x)\nx = 1\n"
        graph = _graph(source)
        edges = _dfg_edges(graph)
        # `x` is used before it's ever defined; no DFG_REACHES edge should
        # claim a definition reaches a use that precedes it in flow.
        assert not any(t == _identifier_at_line(graph, 1, occurrence=1) for _s, t in edges)

    def test_redefinition_kills_the_earlier_one(self) -> None:
        source = "x = 1\nx = 2\ny = x\n"
        graph = _graph(source)
        first_def = _identifier_at_line(graph, 1)
        second_def = _identifier_at_line(graph, 2)
        use_id = _identifier_at_line(graph, 3, occurrence=1)
        edges = _dfg_edges(graph)
        assert (second_def, use_id) in edges
        assert (first_def, use_id) not in edges


class TestBranching:
    def test_both_branch_definitions_reach_the_join(self) -> None:
        source = "if a:\n    x = 1\nelse:\n    x = 2\nprint(x)\n"
        graph = _graph(source)
        then_def = _identifier_at_line(graph, 2)
        else_def = _identifier_at_line(graph, 4)
        use_id = _identifier_at_line(graph, 5, occurrence=1)
        edges = _dfg_edges(graph)
        assert (then_def, use_id) in edges
        assert (else_def, use_id) in edges

    def test_definition_only_on_one_branch_still_reaches_after(self) -> None:
        source = "x = 0\nif a:\n    x = 1\nprint(x)\n"
        graph = _graph(source)
        outer_def = _identifier_at_line(graph, 1)
        branch_def = _identifier_at_line(graph, 3)
        use_id = _identifier_at_line(graph, 4, occurrence=1)
        edges = _dfg_edges(graph)
        # Both the "if taken" and "if skipped" paths must reach the use.
        assert (outer_def, use_id) in edges
        assert (branch_def, use_id) in edges

    def test_elif_branch_definition_reaches_the_join(self) -> None:
        source = "if a:\n    x = 1\nelif b:\n    x = 2\nprint(x)\n"
        graph = _graph(source)
        then_def = _identifier_at_line(graph, 2)
        elif_def = _identifier_at_line(graph, 4)
        use_id = _identifier_at_line(graph, 5, occurrence=1)
        edges = _dfg_edges(graph)
        assert (then_def, use_id) in edges
        assert (elif_def, use_id) in edges


class TestClassBody:
    def test_class_body_statements_are_recorded_as_their_own_scope(self) -> None:
        source = "class Foo:\n    x = 1\n    y = x\n"
        graph = _graph(source)
        def_id = _identifier_at_line(graph, 2)
        use_id = _identifier_at_line(graph, 3, occurrence=1)
        edges = _dfg_edges(graph)
        assert (def_id, use_id) in edges


class TestWithStatement:
    def test_with_statement_context_manager_expression_is_a_use(self) -> None:
        source = "def f(cm):\n    with cm:\n        pass\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)
        use_id = _identifier_at_line(graph, 2)  # `cm` in `with cm:`
        edges = _dfg_edges(graph)
        assert (param_id, use_id) in edges


class TestLoops:
    def test_definition_reaches_across_a_loop_iteration(self) -> None:
        source = "x = 0\nwhile a:\n    x = x + 1\n"
        graph = _graph(source)
        outer_def = _identifier_at_line(graph, 1)
        loop_def = _identifier_at_line(graph, 3)
        loop_use = _identifier_at_line(graph, 3, occurrence=1)  # the `x` on the RHS
        edges = _dfg_edges(graph)
        # First iteration sees the outer def; later iterations see the
        # loop's own previous-iteration def (a real self-referential edge).
        assert (outer_def, loop_use) in edges
        assert (loop_def, loop_use) in edges


class TestAugmentedAssignment:
    def test_augmented_assignment_both_uses_and_redefines(self) -> None:
        source = "x = 1\nx += 1\ny = x\n"
        graph = _graph(source)
        first_def = _identifier_at_line(graph, 1)
        aug_target = _identifier_at_line(graph, 2)  # the `x` in `x += 1`
        final_use = _identifier_at_line(graph, 3, occurrence=1)
        edges = _dfg_edges(graph)
        assert (first_def, aug_target) in edges  # `x`'s prior value is read
        assert (aug_target, final_use) in edges  # then the new value flows on

    def test_augmented_assignment_to_attribute_target_is_a_use(self) -> None:
        # `self.x += 1` — the target isn't a plain identifier, so it must be
        # treated as a use of `self` (via `_collect_uses`), not crash or be
        # silently dropped.
        source = "def f(self):\n    self.x += 1\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)
        edges = _dfg_edges(graph)
        assert any(s == param_id for s, _t in edges)


class TestFunctionParameters:
    def test_parameter_reaches_first_use_in_body(self) -> None:
        source = "def f(a):\n    print(a)\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)  # `a` in the parameter list
        use_id = _identifier_at_line(graph, 2, occurrence=1)  # `a` inside print(a)
        edges = _dfg_edges(graph)
        assert (param_id, use_id) in edges

    def test_parameter_reaches_use_after_an_intervening_statement(self) -> None:
        source = "def f(a):\n    y = 1\n    print(a)\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)
        use_id = _identifier_at_line(graph, 3, occurrence=1)
        edges = _dfg_edges(graph)
        assert (param_id, use_id) in edges

    def test_nested_function_parameters_do_not_leak_to_sibling_function(self) -> None:
        source = "def f(a):\n    print(a)\n\ndef g(b):\n    print(a)\n"
        graph = _graph(source)
        f_param = _parameter_at_line(graph, 1)
        g_use = _identifier_at_line(graph, 5, occurrence=1)  # `a` inside g — never defined there
        edges = _dfg_edges(graph)
        assert (f_param, g_use) not in edges


class TestAttributeAndKeywordExclusions:
    def test_attribute_member_name_is_not_a_definition_or_use(self) -> None:
        # `request.args` — only `request` is a variable reference; `args` is
        # a member name and must not appear as a DFG endpoint.
        source = "def f(request):\n    x = request.args\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)
        edges = _dfg_edges(graph)
        assert any(s == param_id for s, _t in edges)
        # The member name `args` must not itself become a use endpoint.
        args_nodes = [
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind is NodeKind.IDENTIFIER
            and graph.location_of(node_id).start_line == 2
            and graph.location_of(node_id).start_col > graph.location_of(param_id).start_col + 10
        ]
        assert not any(t in args_nodes for _s, t in edges)

    def test_keyword_argument_name_is_not_a_use(self) -> None:
        source = "def f(timeout):\n    call(timeout=timeout)\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)
        edges = _dfg_edges(graph)
        # The parameter must reach the keyword's *value* (second `timeout`),
        # not be conflated with the keyword *name* (first `timeout` in the call).
        assert any(s == param_id for s, _t in edges)


class TestOutOfScopeTargets:
    def test_attribute_assignment_target_is_a_use_not_a_definition(self) -> None:
        # `self.x = 1` does not define a new local variable `x`; `self` is a
        # use (documented scope limit — see module docstring).
        source = "def f(self):\n    self.x = 1\n"
        graph = _graph(source)
        param_id = _parameter_at_line(graph, 1)
        edges = _dfg_edges(graph)
        assert any(s == param_id for s, _t in edges)


class _FakeNode:
    """A minimal stand-in for tree-sitter's `Node`, covering only the
    surface the DFG builder's internals touch: `.type`, `.named_children`,
    `.child_by_field_name`, `.children`/`.child_count`/`.field_name_for_child`
    (for alternative-field scanning), and `.start_byte`/`.end_byte` (for
    `_text`/`ts_node_key`).
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
        self.children = list(named_children)
        self._fields = fields or {}
        self.start_byte = start_byte
        self.end_byte = end_byte

    @property
    def child_count(self) -> int:
        return len(self.children)

    def child_by_field_name(self, name: str) -> object | None:
        return self._fields.get(name)

    def field_name_for_child(self, index: int) -> str | None:
        return None


class TestMalformedTreeDefenses:
    """Direct tests of internal guards against incomplete/malformed parse
    trees (see `test_cfg_builder.TestMalformedTreeDefenses` for the same
    rationale): tree-sitter is error-tolerant and can produce trees a
    syntactically valid Python grammar would never contain.
    """

    def test_collect_uses_tolerates_an_attribute_with_no_object_field(self) -> None:
        out: list[tuple[str, str]] = []
        _collect_uses(_FakeNode("attribute"), node_ids={}, source=b"", out=out)  # type: ignore[arg-type]
        assert out == []

    def test_collect_uses_tolerates_a_keyword_argument_with_no_value_field(self) -> None:
        out: list[tuple[str, str]] = []
        _collect_uses(_FakeNode("keyword_argument"), node_ids={}, source=b"", out=out)  # type: ignore[arg-type]
        assert out == []

    def test_plain_assignment_tolerates_missing_left_and_right_fields(self) -> None:
        defs, uses = _extract_plain_assignment(
            _FakeNode("assignment"),  # type: ignore[arg-type]
            node_ids={},
            source=b"",
        )
        assert defs == []
        assert uses == []

    def test_augmented_assignment_tolerates_missing_left_and_right_fields(self) -> None:
        defs, uses = _extract_augmented_assignment(
            _FakeNode("augmented_assignment"),  # type: ignore[arg-type]
            node_ids={},
            source=b"",
        )
        assert defs == []
        assert uses == []

    def test_extract_defs_uses_tolerates_a_condition_statement_with_no_condition_field(
        self,
    ) -> None:
        defs, uses = _extract_defs_uses(
            _FakeNode("if_statement"),  # type: ignore[arg-type]
            node_ids={},
            source=b"",
        )
        assert defs == []
        assert uses == []

    def test_parameter_defs_tolerates_a_missing_parameters_field(self) -> None:
        result = _parameter_defs(
            _FakeNode("function_definition"),  # type: ignore[arg-type]
            node_ids={},
            source=b"",
        )
        assert result == []

    def test_parameter_defs_skips_a_parameter_with_no_identifiable_name(self) -> None:
        good_param = _FakeNode("identifier", start_byte=0, end_byte=1)
        bad_param = _FakeNode("tuple_pattern")  # no "name" field, not itself an identifier
        params_node = _FakeNode("parameters", named_children=(bad_param, good_param))
        function_node = _FakeNode("function_definition", fields={"parameters": params_node})
        node_ids = {ts_node_key(good_param): "n1"}  # type: ignore[arg-type]
        result = _parameter_defs(function_node, node_ids=node_ids, source=b"a")  # type: ignore[arg-type]
        assert result == [("a", "n1")]

    def test_visit_scope_definition_tolerates_a_missing_body_field(self) -> None:
        collector = _DataFlowCollector(node_ids={}, source=b"")
        collector._visit_scope_definition(_FakeNode("function_definition"))  # type: ignore[arg-type]
        assert collector.program_points == {}
        assert collector.entry_seeds == {}

    def test_visit_if_like_tolerates_a_missing_consequence_field(self) -> None:
        fake_if = _FakeNode("if_statement", start_byte=0, end_byte=1)
        node_ids = {ts_node_key(fake_if): "n-if"}  # type: ignore[arg-type]
        collector = _DataFlowCollector(node_ids=node_ids, source=b"")
        collector._visit_if_like(fake_if)  # type: ignore[arg-type]
        assert "n-if" in collector.program_points

    def test_walk_else_tolerates_a_missing_body_field(self) -> None:
        collector = _DataFlowCollector(node_ids={}, source=b"")
        collector._walk_else(_FakeNode("else_clause"))  # type: ignore[arg-type]
        assert collector.program_points == {}

    def test_visit_statement_tolerates_a_loop_with_no_body_field(self) -> None:
        fake_while = _FakeNode("while_statement", start_byte=0, end_byte=1)
        node_ids = {ts_node_key(fake_while): "n-while"}  # type: ignore[arg-type]
        collector = _DataFlowCollector(node_ids=node_ids, source=b"")
        collector._visit_statement(fake_while)  # type: ignore[arg-type]
        assert "n-while" in collector.program_points
