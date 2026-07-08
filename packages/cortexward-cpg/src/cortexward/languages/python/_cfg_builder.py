"""Populates CFG_NEXT edges over the AST layer built by ``_ast_walker``.

Runs as a second pass over the *same* tree-sitter tree, using the
``node_ids`` mapping :func:`~cortexward.languages.python._ast_walker.
walk_module` produced, so edges land on the exact graph nodes the AST layer
already created.

**Scope of this pass:** sequential statement flow, ``if``/``elif``/``else``
branching, ``while``/``for`` loops (incl. ``break``/``continue``), ``with``
blocks, and ``return``. Each function and class body is its own independent
control-flow scope — a nested ``def``/``class`` is atomic in its enclosing
scope's sequence, with its body's flow built separately.

**Explicitly out of scope:** ``try``/``except``/``finally`` exception control
flow. A ``try_statement`` is left as a plain, atomic statement (no internal
branching edges) — modeling exception paths correctly (each statement can
jump to a handler, `finally` always runs) is substantial enough to warrant
its own dedicated builder rather than an approximation bolted on here.

**A documented simplification:** ``while``/``for`` ``else`` clauses run only
when the loop completes without ``break``; this pass connects the loop
condition to both "loop is done" and the ``else`` block without
distinguishing the break-vs-natural-completion cases precisely. The edges
this adds are all real reachability facts — the imprecision is in not always
separating *why* the loop ended, not in reporting a path that cannot occur.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder
from cortexward.languages.python._ast_walker import TSNodeKey, ts_node_key
from cortexward.ports import NodeId


@dataclass
class _Flow:
    """The control-flow shape of one walked AST construct.

    ``entry`` is the node control enters first (``None`` for an empty/no-op
    construct). ``exits`` fall through to whatever follows in sequence.
    ``returns``/``breaks``/``continues`` are exits that do *not* fall through
    locally: they bubble up to be consumed by the enclosing function
    (``returns``), or the nearest enclosing loop (``breaks`` -> after the
    loop, ``continues`` -> back to the loop's condition).
    """

    entry: NodeId | None
    exits: list[NodeId] = field(default_factory=list)
    returns: list[NodeId] = field(default_factory=list)
    breaks: list[NodeId] = field(default_factory=list)
    continues: list[NodeId] = field(default_factory=list)


def _empty_flow() -> _Flow:
    return _Flow(entry=None)


class _ControlFlowBuilder:
    def __init__(self, *, node_ids: dict[TSNodeKey, NodeId], builder: GraphBuilder) -> None:
        self._node_ids = node_ids
        self._builder = builder
        self._cfg_edges: list[tuple[NodeId, NodeId]] = []
        # Statement types with dedicated control-flow shapes. Anything absent
        # here (including try_statement — see module docstring) falls back
        # to `_flow_for_atomic`.
        self._handlers: dict[str, Callable[[TSNode], _Flow]] = {
            "if_statement": self._flow_for_if_like,
            "while_statement": self._flow_for_loop,
            "for_statement": self._flow_for_loop,
            "with_statement": self._flow_for_with,
            "return_statement": self._flow_for_return,
            "break_statement": self._flow_for_break,
            "continue_statement": self._flow_for_continue,
            "function_definition": self._flow_for_nested_scope,
            "class_definition": self._flow_for_nested_scope,
        }

    def run(self, tree_root: TSNode) -> list[tuple[NodeId, NodeId]]:
        self._build_scope(list(tree_root.named_children))
        return self._cfg_edges

    def _id_of(self, ts_node: TSNode) -> NodeId:
        return self._node_ids[ts_node_key(ts_node)]

    @staticmethod
    def _field_statements(node: TSNode, field_name: str) -> list[TSNode]:
        """The named children of `node`'s `field_name` field (must be present).

        The grammar guarantees this field is populated for every call site
        below (e.g. every `if_statement` has a `consequence`); raising here
        turns a grammar assumption we rely on into a clear failure rather
        than a confusing `AttributeError` if that assumption is ever wrong.
        """
        field_node = node.child_by_field_name(field_name)
        if field_node is None:
            raise ValueError(f"{node.type} missing expected field {field_name!r}")
        return list(field_node.named_children)

    def _connect(self, sources: list[NodeId], target_entry: NodeId | None) -> None:
        if target_entry is None:
            return
        for source in sources:
            self._builder.add_edge(EdgeKind.CFG_NEXT, source, target_entry)
            self._cfg_edges.append((source, target_entry))

    def _build_scope(self, statements: list[TSNode]) -> None:
        """Build the CFG for one independent scope (module/function/class body).

        The resulting flow's dangling ends (`exits`/`returns`/stray
        `breaks`/`continues`) are the scope's boundary — nothing outside
        this pass connects to them, so the result is intentionally discarded.
        """
        self._flow_for_sequence(statements)

    def _flow_for_sequence(self, statements: list[TSNode]) -> _Flow:
        overall = _empty_flow()
        previous_exits: list[NodeId] = []
        for stmt in statements:
            stmt_flow = self._flow_for_statement(stmt)
            if stmt_flow.entry is None:
                continue
            if overall.entry is None:
                overall.entry = stmt_flow.entry
            self._connect(previous_exits, stmt_flow.entry)
            previous_exits = stmt_flow.exits
            overall.returns.extend(stmt_flow.returns)
            overall.breaks.extend(stmt_flow.breaks)
            overall.continues.extend(stmt_flow.continues)
        overall.exits = previous_exits
        return overall

    def _flow_for_statement(self, ts_node: TSNode) -> _Flow:
        handler = self._handlers.get(ts_node.type)
        if handler is None:
            return self._flow_for_atomic(ts_node)
        return handler(ts_node)

    def _flow_for_atomic(self, ts_node: TSNode) -> _Flow:
        """The default shape: enters and, normally, exits through itself.

        Used for any statement without a dedicated handler above, including
        `try_statement` (see module docstring) and simple statements
        (assignments, expression statements, imports, ...).
        """
        node_id = self._id_of(ts_node)
        return _Flow(entry=node_id, exits=[node_id])

    def _flow_for_return(self, ts_node: TSNode) -> _Flow:
        node_id = self._id_of(ts_node)
        return _Flow(entry=node_id, returns=[node_id])

    def _flow_for_break(self, ts_node: TSNode) -> _Flow:
        node_id = self._id_of(ts_node)
        return _Flow(entry=node_id, breaks=[node_id])

    def _flow_for_continue(self, ts_node: TSNode) -> _Flow:
        node_id = self._id_of(ts_node)
        return _Flow(entry=node_id, continues=[node_id])

    def _flow_for_nested_scope(self, ts_node: TSNode) -> _Flow:
        """A nested `def`/`class`: atomic here, its body is its own scope."""
        node_id = self._id_of(ts_node)
        self._build_scope(self._field_statements(ts_node, "body"))
        return _Flow(entry=node_id, exits=[node_id])

    def _flow_for_if_like(self, node: TSNode) -> _Flow:
        """Handles `if_statement`.

        tree-sitter models an ``if``/``elif``/.../``else`` chain as *flat*
        siblings of the original ``if_statement`` (each tagged with field
        name ``alternative``) — an ``elif_clause`` has no ``alternative``
        field of its own. ``_connect_alternatives`` threads the "condition
        false" path explicitly through the remaining siblings instead of
        assuming each ``elif_clause`` nests the next one.
        """
        node_id = self._id_of(node)
        alternatives = [
            node.children[i]
            for i in range(node.child_count)
            if node.field_name_for_child(i) == "alternative"
        ]

        result = _Flow(entry=node_id)
        true_flow = self._flow_for_sequence(self._field_statements(node, "consequence"))
        self._connect([node_id], true_flow.entry)
        result.exits.extend(true_flow.exits)
        result.returns.extend(true_flow.returns)
        result.breaks.extend(true_flow.breaks)
        result.continues.extend(true_flow.continues)

        self._connect_alternatives(node_id, alternatives, result)
        return result

    def _connect_alternatives(
        self, from_id: NodeId, alternatives: list[TSNode], result: _Flow
    ) -> None:
        """Wires the "condition false" path through a flat elif/else chain.

        Mutates `result` in place, accumulating exits/returns/breaks/
        continues from whichever alternative ends up executing.
        """
        if not alternatives:
            # No (more) alternatives: the false path skips straight past.
            result.exits.append(from_id)
            return

        head, *rest = alternatives
        if head.type == "elif_clause":
            head_id = self._id_of(head)
            self._connect([from_id], head_id)
            head_flow = self._flow_for_sequence(self._field_statements(head, "consequence"))
            self._connect([head_id], head_flow.entry)
            result.exits.extend(head_flow.exits)
            result.returns.extend(head_flow.returns)
            result.breaks.extend(head_flow.breaks)
            result.continues.extend(head_flow.continues)
            # This elif's own false path continues down the remaining chain.
            self._connect_alternatives(head_id, rest, result)
        else:  # else_clause — always terminal, no further chaining
            else_flow = self._flow_for_sequence(self._field_statements(head, "body"))
            self._connect([from_id], else_flow.entry)
            result.exits.extend(else_flow.exits)
            result.returns.extend(else_flow.returns)
            result.breaks.extend(else_flow.breaks)
            result.continues.extend(else_flow.continues)

    def _flow_for_loop(self, node: TSNode) -> _Flow:
        node_id = self._id_of(node)
        body_flow = self._flow_for_sequence(self._field_statements(node, "body"))

        self._connect([node_id], body_flow.entry)  # condition/iterator true -> body
        self._connect(body_flow.exits, node_id)  # body falls through -> re-check
        self._connect(body_flow.continues, node_id)  # continue -> re-check

        result = _Flow(entry=node_id)
        result.exits.append(node_id)  # condition/iterator false -> falls through
        result.exits.extend(body_flow.breaks)  # break -> escapes the loop
        result.returns.extend(body_flow.returns)  # return bubbles past the loop

        alternative = node.child_by_field_name("alternative")
        if alternative is not None and alternative.type == "else_clause":
            else_flow = self._flow_for_sequence(self._field_statements(alternative, "body"))
            self._connect([node_id], else_flow.entry)
            result.exits.extend(else_flow.exits)
            result.returns.extend(else_flow.returns)

        return result

    def _flow_for_with(self, node: TSNode) -> _Flow:
        node_id = self._id_of(node)
        body_flow = self._flow_for_sequence(self._field_statements(node, "body"))
        self._connect([node_id], body_flow.entry)
        return _Flow(
            entry=node_id,
            exits=body_flow.exits,
            returns=body_flow.returns,
            breaks=body_flow.breaks,
            continues=body_flow.continues,
        )


def build_control_flow(
    tree_root: TSNode, *, node_ids: dict[TSNodeKey, NodeId], builder: GraphBuilder
) -> list[tuple[NodeId, NodeId]]:
    """Populate CFG_NEXT edges for every scope in `tree_root`.

    Covers the module's top level and every nested function/class body,
    using `node_ids` (from `walk_module`) to attach edges to the graph nodes
    the AST layer already created. Returns every (source, target) CFG_NEXT
    edge added, so a later pass (the data-flow builder) can run a
    reaching-definitions analysis over the same graph without re-deriving it.
    """
    return _ControlFlowBuilder(node_ids=node_ids, builder=builder).run(tree_root)
