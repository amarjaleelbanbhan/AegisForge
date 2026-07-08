"""Populates CALLS edges by resolving call sites to function/method definitions.

Runs as a pass over the same tree-sitter tree, using the ``node_ids`` mapping
:func:`~cortexward.languages.python._ast_walker.walk_module` produced.

**Resolution strategy:** best-effort, same-file, name-based resolution — not
full type inference (running the analyzed code to resolve types precisely is
out of scope, per ADR-0004). Two call shapes are resolved:

- A bare call whose callee is a plain identifier (``foo()``) resolves to
  every module- or nested-scope function definition with that name in the
  same file, excluding methods (functions defined directly in a class body).
- A method call whose callee is an attribute access (``obj.method()`` or
  ``self.method()``) resolves to every method definition with that name, in
  any class body in the same file.

Either shape can resolve to more than one definition (e.g. two unrelated
classes each defining a same-named method) — every match gets its own CALLS
edge. This is a deliberate over-approximation: for reachability/taint
analysis, a missed edge is worse than an imprecise one, and precise
resolution needs a real symbol table (future dependency-graph work).

**Explicitly out of scope:** cross-file resolution, imported-symbol
resolution, dynamic dispatch precision (``getattr``, decorators rewriting the
call target), and calls with no matching in-file definition (builtins like
``print()``, stdlib calls) — these simply get no CALLS edge, not an error.
"""

from __future__ import annotations

from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder
from cortexward.languages.python._ast_walker import TSNodeKey, ts_node_key
from cortexward.ports import NodeId

_DefinitionsByName = dict[str, list[NodeId]]


def _text(node: TSNode, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _collect_definitions(
    node: TSNode,
    *,
    node_ids: dict[TSNodeKey, NodeId],
    source: bytes,
    in_class: bool,
    plain: _DefinitionsByName,
    methods: _DefinitionsByName,
) -> None:
    """Populates `plain`/`methods` with every function definition's name -> node id(s).

    A function defined directly in a class body is a method; a function
    nested inside *that* method's own body is not (`in_class` resets to
    `False` when descending into any function's body, regardless of the
    enclosing class).
    """
    if node.type == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            table = methods if in_class else plain
            table.setdefault(_text(name_node, source), []).append(node_ids[ts_node_key(node)])
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.named_children:
                _collect_definitions(
                    child,
                    node_ids=node_ids,
                    source=source,
                    in_class=False,
                    plain=plain,
                    methods=methods,
                )
        return
    if node.type == "class_definition":
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.named_children:
                _collect_definitions(
                    child,
                    node_ids=node_ids,
                    source=source,
                    in_class=True,
                    plain=plain,
                    methods=methods,
                )
        return
    for child in node.named_children:
        _collect_definitions(
            child, node_ids=node_ids, source=source, in_class=in_class, plain=plain, methods=methods
        )


def _resolve_callee(
    callee: TSNode, *, source: bytes, plain: _DefinitionsByName, methods: _DefinitionsByName
) -> list[NodeId]:
    if callee.type == "identifier":
        return plain.get(_text(callee, source), [])
    if callee.type == "attribute":
        attribute = callee.child_by_field_name("attribute")
        if attribute is not None and attribute.type == "identifier":
            return methods.get(_text(attribute, source), [])
    return []


def _resolve_calls(
    node: TSNode,
    *,
    node_ids: dict[TSNodeKey, NodeId],
    source: bytes,
    plain: _DefinitionsByName,
    methods: _DefinitionsByName,
    builder: GraphBuilder,
) -> None:
    if node.type == "call":
        callee = node.child_by_field_name("function")
        if callee is not None:
            call_id = node_ids[ts_node_key(node)]
            for target_id in _resolve_callee(callee, source=source, plain=plain, methods=methods):
                builder.add_edge(EdgeKind.CALLS, call_id, target_id)
    for child in node.named_children:
        _resolve_calls(
            child, node_ids=node_ids, source=source, plain=plain, methods=methods, builder=builder
        )


def build_call_graph(
    tree_root: TSNode,
    *,
    node_ids: dict[TSNodeKey, NodeId],
    source: bytes,
    builder: GraphBuilder,
) -> None:
    """Populate CALLS edges for every resolvable call site in `tree_root`."""
    plain: _DefinitionsByName = {}
    methods: _DefinitionsByName = {}
    _collect_definitions(
        tree_root, node_ids=node_ids, source=source, in_class=False, plain=plain, methods=methods
    )
    _resolve_calls(
        tree_root, node_ids=node_ids, source=source, plain=plain, methods=methods, builder=builder
    )
