"""Unit tests for the control-flow (CFG_NEXT) builder.

CFG_NEXT edges connect at *statement* granularity: a bare expression like
`x = 1` is wrapped by tree-sitter as `expression_statement(assignment(...))`,
and it is the `expression_statement` — the direct child of a block — that
participates in sequencing, not the nested `assignment` expression (that
distinction matters for a future data-flow builder, not control flow). Tests
below query `expression_statement` nodes for CFG-connectivity assertions.
"""

from __future__ import annotations

import pytest
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder, InMemoryCodeGraph, NodeKind
from cortexward.languages.python._ast_walker import walk_module
from cortexward.languages.python._cfg_builder import _ControlFlowBuilder, _Flow, build_control_flow

pytestmark = pytest.mark.unit

_PARSER = Parser(Language(tspython.language()))


def _parse(source: str) -> TSNode:
    return _PARSER.parse(source.encode("utf-8")).root_node


def _graph(source: str, file_path: str = "app.py") -> InMemoryCodeGraph:
    builder = GraphBuilder(language="python")
    root = _parse(source)
    result = walk_module(root, source=source.encode("utf-8"), file_path=file_path, builder=builder)
    build_control_flow(root, node_ids=result.node_ids, builder=builder)
    return builder.build()


def _cfg_edges(graph: InMemoryCodeGraph) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in graph.edges if e.kind is EdgeKind.CFG_NEXT}


def _by_kind(graph: InMemoryCodeGraph, kind: NodeKind) -> list[str]:
    return [node_id for node_id, node in graph.nodes.items() if node.kind is kind]


def _statement_node(graph: InMemoryCodeGraph, ts_type: str, name: str | None = None) -> str:
    """The single node whose properties match `ts_type` (and `name`, if given)."""
    matches = [
        node_id
        for node_id, node in graph.nodes.items()
        if node.properties.get("ts_type") == ts_type
        and (name is None or node.properties.get("name") == name)
    ]
    assert len(matches) == 1, f"expected exactly one {ts_type!r} node, found {len(matches)}"
    return matches[0]


def _expr_statements(graph: InMemoryCodeGraph) -> list[str]:
    """Every `expression_statement` node (e.g. an assignment line), by source order.

    This is the CFG-connected statement level for a bare expression like
    `x = 1` — see the module docstring.
    """
    matches = [
        node_id
        for node_id, node in graph.nodes.items()
        if node.properties.get("ts_type") == "expression_statement"
    ]
    return sorted(matches, key=lambda n: graph.location_of(n).start_line)


class TestSequentialFlow:
    def test_statements_connect_in_order(self) -> None:
        graph = _graph("x = 1\ny = 2\nz = 3\n")
        statements = _expr_statements(graph)
        assert len(statements) == 3
        edges = _cfg_edges(graph)
        assert (statements[0], statements[1]) in edges
        assert (statements[1], statements[2]) in edges

    def test_reachable_across_sequential_statements(self) -> None:
        graph = _graph("x = 1\ny = 2\n")
        first, last = _expr_statements(graph)
        assert graph.reachable([first], last) is True


class TestIfElse:
    def test_if_without_else_skips_forward(self) -> None:
        source = "if a:\n    x = 1\nz = 2\n"
        graph = _graph(source)
        if_id = _statement_node(graph, "if_statement")
        z_id = _expr_statements(graph)[-1]  # the later, top-level `z = 2`
        # Both the true-branch exit and the false (skip) path must reach `z`.
        assert graph.reachable([if_id], z_id) is True

    def test_if_else_both_branches_converge(self) -> None:
        source = "if a:\n    x = 1\nelse:\n    x = 2\nz = 3\n"
        graph = _graph(source)
        edges = _cfg_edges(graph)
        if_id = _statement_node(graph, "if_statement")
        # Exactly two outgoing edges from the if: true-branch and else-branch entries.
        outgoing = {t for s, t in edges if s == if_id}
        assert len(outgoing) == 2

    def test_elif_chain(self) -> None:
        source = "if a:\n    x = 1\nelif b:\n    x = 2\nelif c:\n    x = 3\nelse:\n    x = 4\n"
        graph = _graph(source)
        if_id = _statement_node(graph, "if_statement")
        branch_nodes = _by_kind(graph, NodeKind.BRANCH)
        assert len(branch_nodes) == 3  # if_statement + 2 elif_clauses (each tagged BRANCH)
        # Every branch of the chain (if / elif / elif / else) must be
        # reachable from the top of the if.
        statements = _expr_statements(graph)
        assert len(statements) == 4
        assert all(graph.reachable([if_id], stmt) for stmt in statements)

    def test_elif_chain_branches_do_not_reach_each_other(self) -> None:
        # Each branch's body must be mutually exclusive from the others:
        # taking the `if` branch cannot also reach the `elif`/`else` bodies.
        source = "if a:\n    x = 1\nelif b:\n    x = 2\nelse:\n    x = 3\n"
        graph = _graph(source)
        first_branch, second_branch, third_branch = _expr_statements(graph)
        assert graph.reachable([first_branch], second_branch) is False
        assert graph.reachable([first_branch], third_branch) is False


class TestWhileLoop:
    def test_body_loops_back_to_condition(self) -> None:
        source = "while a:\n    x = 1\n"
        graph = _graph(source)
        while_id = _statement_node(graph, "while_statement")
        (body_id,) = _expr_statements(graph)
        edges = _cfg_edges(graph)
        assert (while_id, body_id) in edges
        assert (body_id, while_id) in edges

    def test_break_escapes_the_loop(self) -> None:
        source = "while a:\n    if b:\n        break\n    x = 1\nz = 2\n"
        graph = _graph(source)
        while_id = _statement_node(graph, "while_statement")
        z_id = _expr_statements(graph)[-1]  # the later, top-level `z = 2`
        assert graph.reachable([while_id], z_id) is True
        break_id = _statement_node(graph, "break_statement")
        edges = _cfg_edges(graph)
        assert (break_id, z_id) in edges

    def test_continue_returns_to_condition_not_forward(self) -> None:
        source = "while a:\n    if b:\n        continue\n    x = 1\n"
        graph = _graph(source)
        while_id = _statement_node(graph, "while_statement")
        continue_id = _statement_node(graph, "continue_statement")
        (x_id,) = _expr_statements(graph)
        edges = _cfg_edges(graph)
        assert (continue_id, while_id) in edges
        assert (continue_id, x_id) not in edges

    def test_while_else_runs_when_loop_condition_becomes_false(self) -> None:
        source = "while a:\n    x = 1\nelse:\n    y = 2\n"
        graph = _graph(source)
        while_id = _statement_node(graph, "while_statement")
        else_body_id = _expr_statements(graph)[-1]  # the later `y = 2`, in the else clause
        # else body reachable from the loop header (condition-false path).
        assert graph.reachable([while_id], else_body_id) is True


class TestForLoop:
    def test_for_loop_body_connects_back(self) -> None:
        source = "for i in items:\n    x = i\n"
        graph = _graph(source)
        for_id = _statement_node(graph, "for_statement")
        (body_id,) = _expr_statements(graph)
        edges = _cfg_edges(graph)
        assert (for_id, body_id) in edges
        assert (body_id, for_id) in edges


class TestWithStatement:
    def test_with_block_is_transparent_to_flow(self) -> None:
        source = 'with open("f") as fh:\n    x = 1\ny = 2\n'
        graph = _graph(source)
        with_id = _statement_node(graph, "with_statement")
        body_id, y_id = _expr_statements(graph)
        edges = _cfg_edges(graph)
        assert (with_id, body_id) in edges
        assert (body_id, y_id) in edges

    def test_return_inside_with_bubbles_past_it(self) -> None:
        source = 'def f():\n    with open("g") as fh:\n        return 1\n    z = 2\n'
        graph = _graph(source)
        return_id = _statement_node(graph, "return_statement")
        (z_id,) = _expr_statements(graph)
        edges = _cfg_edges(graph)
        # `return` never falls through to whatever follows the with-block.
        assert (return_id, z_id) not in edges


class TestReturnBubbling:
    def test_return_does_not_connect_to_following_statement(self) -> None:
        source = "def f():\n    return 1\n    x = 2\n"
        graph = _graph(source)
        return_id = _statement_node(graph, "return_statement")
        (x_id,) = _expr_statements(graph)
        edges = _cfg_edges(graph)
        assert (return_id, x_id) not in edges

    def test_return_inside_if_bubbles_through(self) -> None:
        source = "def f(a):\n    if a:\n        return 1\n    return 2\n"
        graph = _graph(source)
        return_ids = _by_kind(graph, NodeKind.RETURN)
        assert len(return_ids) == 2
        # Neither return should have an outgoing CFG_NEXT edge to the other.
        edges = _cfg_edges(graph)
        assert not any(s in return_ids and t in return_ids for s, t in edges)

    def test_return_inside_loop_escapes_it(self) -> None:
        source = "def f(a):\n    while a:\n        return 1\n    return 2\n"
        graph = _graph(source)
        while_id = _statement_node(graph, "while_statement")
        return_ids = _by_kind(graph, NodeKind.RETURN)
        edges = _cfg_edges(graph)
        # The return inside the loop must not create a loop-back edge to the
        # while condition (that would misrepresent it as a normal exit).
        assert not any(s in return_ids and t == while_id for s, t in edges)


class TestNestedScopes:
    def test_function_is_atomic_in_enclosing_sequence(self) -> None:
        source = "def f():\n    x = 1\n\ndef g():\n    y = 2\n"
        graph = _graph(source)
        f_id = _statement_node(graph, "function_definition", name="f")
        g_id = _statement_node(graph, "function_definition", name="g")
        edges = _cfg_edges(graph)
        assert (f_id, g_id) in edges

    def test_nested_function_bodies_are_independent(self) -> None:
        source = "def f():\n    x = 1\n\ndef g():\n    y = 2\n"
        graph = _graph(source)
        x_id, y_id = _expr_statements(graph)
        # f's body and g's body must not be CFG-connected to each other.
        assert graph.reachable([x_id], y_id) is False

    def test_class_body_gets_its_own_sequential_flow(self) -> None:
        source = "class Foo:\n    x = 1\n    y = 2\n"
        graph = _graph(source)
        statements = _expr_statements(graph)
        assert len(statements) == 2
        edges = _cfg_edges(graph)
        assert (statements[0], statements[1]) in edges


class TestTryStatementOutOfScope:
    def test_try_statement_has_no_internal_cfg_edges(self) -> None:
        # try/except is explicitly out of scope for this builder (see module
        # docstring): the try_statement is atomic, its internal statements
        # get AST nodes but no CFG_NEXT edges among them from this pass.
        source = "try:\n    x = 1\nexcept ValueError:\n    x = 2\n"
        graph = _graph(source)
        try_id = _statement_node(graph, "try_statement")
        statements = _expr_statements(graph)
        assert len(statements) == 2
        edges = _cfg_edges(graph)
        assert not any(try_id in (s, t) for s, t in edges)
        assert not any(s in statements and t in statements for s, t in edges)


class TestMalformedTreeDefenses:
    """Direct tests of internal guards against incomplete/malformed parse
    trees. tree-sitter is error-tolerant and can produce trees a
    syntactically valid Python grammar would never contain (e.g. from a
    truncated file); this system treats parsed input as untrusted (ADR-0004)
    and must not crash confusingly on it.
    """

    def test_field_statements_raises_on_missing_field(self) -> None:
        # A `module` node has no `consequence` field; `_field_statements`
        # must fail clearly rather than raise a bare AttributeError deeper in
        # tree-sitter's bindings.
        root = _parse("x = 1\n")
        cfg_builder = _ControlFlowBuilder(node_ids={}, builder=GraphBuilder(language="python"))
        with pytest.raises(ValueError, match="missing expected field"):
            cfg_builder._field_statements(root, "consequence")

    def test_connect_to_a_none_entry_is_a_no_op(self) -> None:
        # _flow_for_sequence([]) — an empty statement list — has no entry to
        # connect to; _connect must tolerate that silently rather than fail.
        builder = GraphBuilder(language="python")
        cfg_builder = _ControlFlowBuilder(node_ids={}, builder=builder)
        cfg_builder._connect(["some-source"], None)
        assert builder.build().edges == ()

    def test_sequence_skips_a_statement_reporting_no_entry(self) -> None:
        # A statement whose flow has no entry (a no-op construct) must be
        # skipped when stitching a sequence together, rather than treated as
        # a real predecessor/successor.
        source = "x = 1\ny = 2\n"
        root = _parse(source)
        builder = GraphBuilder(language="python")
        result = walk_module(
            root, source=source.encode("utf-8"), file_path="app.py", builder=builder
        )
        cfg_builder = _ControlFlowBuilder(node_ids=result.node_ids, builder=builder)
        statements = list(root.named_children)
        real_flow_for_statement = cfg_builder._flow_for_statement

        def _report_first_as_empty(ts_node: TSNode) -> _Flow:
            if ts_node is statements[0]:
                return _Flow(entry=None)
            return real_flow_for_statement(ts_node)

        cfg_builder._flow_for_statement = _report_first_as_empty  # type: ignore[method-assign]
        flow = cfg_builder._flow_for_sequence(statements)
        assert flow.entry == cfg_builder._id_of(statements[1])
