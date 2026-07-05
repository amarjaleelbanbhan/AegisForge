"""Walks a tree-sitter Python parse tree into the CPG schema.

This produces the **AST layer** of the Code Property Graph only: nodes for
syntactic constructs, connected by ``AST_CHILD`` edges. Control-flow
(``CFG_NEXT``), data-flow (``DFG_REACHES``), and call-resolution (``CALLS``)
edges are populated by separate builders (later Phase 2 milestones) that
walk this same AST layer; this module does not fabricate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder, NodeKind
from cortexward.domain import SourceLocation
from cortexward.ports import NodeId

TSNodeKey = tuple[int, int, str]
"""A stable identity key for a tree-sitter node: (start_byte, end_byte, type).

tree-sitter's Python ``Node`` wrapper objects are not necessarily the same
*object* across separate accesses to "the same" underlying node (they can be
recreated on each attribute access), so ``id(ts_node)`` is not a safe cross-
pass identity — a wrapper object can be garbage-collected and its address
reused, silently aliasing an unrelated later node. ``(start_byte, end_byte,
type)`` is intrinsic to the node's position and kind, stable across any
number of separate traversals of the same parse tree. A wrapper node sharing
its child's exact byte range (e.g. ``expression_statement`` around a lone
``call``) is still disambiguated by ``type``.
"""


def ts_node_key(ts_node: TSNode) -> TSNodeKey:
    return (ts_node.start_byte, ts_node.end_byte, ts_node.type)


@dataclass
class WalkResult:
    """The output of one :func:`walk_module` call.

    ``node_ids`` maps each tree-sitter node (by its stable :data:`TSNodeKey`,
    via :func:`ts_node_key`) to the graph :data:`NodeId` created for it. Later
    passes over the *same* tree (e.g. the control-flow builder) use this to
    attach further edges to the exact nodes the AST layer already created,
    without recomputing or guessing the id scheme.
    """

    module_id: NodeId
    node_ids: dict[TSNodeKey, NodeId] = field(default_factory=dict)


# Direct mapping from a tree-sitter node type to our language-agnostic schema.
# Types not listed here fall back to NodeKind.OTHER — a faithful "we parsed
# this construct but haven't given it a dedicated kind yet", not an error.
_KIND_BY_TS_TYPE: dict[str, NodeKind] = {
    "module": NodeKind.MODULE,
    "class_definition": NodeKind.CLASS,
    "function_definition": NodeKind.FUNCTION,
    "lambda": NodeKind.FUNCTION,
    "call": NodeKind.CALL,
    "assignment": NodeKind.ASSIGNMENT,
    "augmented_assignment": NodeKind.ASSIGNMENT,
    "named_expression": NodeKind.ASSIGNMENT,
    "if_statement": NodeKind.BRANCH,
    "elif_clause": NodeKind.BRANCH,
    "while_statement": NodeKind.BRANCH,
    "for_statement": NodeKind.BRANCH,
    "try_statement": NodeKind.BRANCH,
    "return_statement": NodeKind.RETURN,
    "yield": NodeKind.RETURN,
    "import_statement": NodeKind.IMPORT,
    "import_from_statement": NodeKind.IMPORT,
    "identifier": NodeKind.IDENTIFIER,
    "integer": NodeKind.LITERAL,
    "float": NodeKind.LITERAL,
    "string": NodeKind.LITERAL,
    "true": NodeKind.LITERAL,
    "false": NodeKind.LITERAL,
    "none": NodeKind.LITERAL,
}

# Parameter-shaped nodes are only PARAMETER when they sit directly under a
# `parameters` node; the same node types (e.g. `identifier`) mean something
# else everywhere else in the tree.
_PARAMETER_TS_TYPES = frozenset(
    {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }
)


def _kind_for(ts_node: TSNode, *, parent_type: str | None) -> NodeKind:
    if parent_type == "parameters" and ts_node.type in _PARAMETER_TS_TYPES:
        return NodeKind.PARAMETER
    return _KIND_BY_TS_TYPE.get(ts_node.type, NodeKind.OTHER)


def _location_for(ts_node: TSNode, path: str) -> SourceLocation:
    start_line = ts_node.start_point[0] + 1
    start_col = ts_node.start_point[1] + 1
    end_line = ts_node.end_point[0] + 1
    end_col = ts_node.end_point[1] + 1
    if end_line == start_line and end_col < start_col:
        end_col = start_col
    return SourceLocation(
        path=path, start_line=start_line, start_col=start_col, end_line=end_line, end_col=end_col
    )


def _node_name(ts_node: TSNode, source: bytes) -> str | None:
    """The `name` field's text, for nodes that have one (function/class defs)."""
    name_node = ts_node.child_by_field_name("name")
    if name_node is None:
        return None
    return source[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")


def _is_main_guard(ts_node: TSNode, source: bytes) -> bool:
    """Whether `ts_node` (an if_statement) is an `if __name__ == "__main__":` guard."""
    condition = ts_node.child_by_field_name("condition")
    if condition is None or condition.type != "comparison_operator":
        return False
    text = source[condition.start_byte : condition.end_byte].decode("utf-8", errors="replace")
    return "__name__" in text and "__main__" in text


def walk_module(
    tree_root: TSNode,
    *,
    source: bytes,
    file_path: str,
    builder: GraphBuilder,
) -> WalkResult:
    """Walk one file's parse tree into `builder`, returning a :class:`WalkResult`.

    Marks entry points heuristically: functions named ``main`` and
    ``if __name__ == "__main__":`` guards. This is a starting heuristic, not
    an exhaustive entry-point analysis (framework-specific routes/handlers
    are future work).
    """
    ids = count()
    node_ids: dict[TSNodeKey, NodeId] = {}

    def _walk(ts_node: TSNode, *, parent_id: NodeId | None, parent_type: str | None) -> NodeId:
        node_id = f"{file_path}#{next(ids)}:{ts_node.type}"
        node_ids[ts_node_key(ts_node)] = node_id
        kind = _kind_for(ts_node, parent_type=parent_type)
        properties: dict[str, str] = {"ts_type": ts_node.type}
        name = _node_name(ts_node, source)
        if name is not None:
            properties["name"] = name

        builder.add_node(node_id, kind, _location_for(ts_node, file_path), properties=properties)
        if parent_id is not None:
            builder.add_edge(EdgeKind.AST_CHILD, parent_id, node_id)

        if kind is NodeKind.FUNCTION and name == "main":
            builder.mark_entrypoint(node_id)
        if ts_node.type == "if_statement" and _is_main_guard(ts_node, source):
            builder.mark_entrypoint(node_id)

        for child in ts_node.named_children:
            _walk(child, parent_id=node_id, parent_type=ts_node.type)
        return node_id

    module_id = _walk(tree_root, parent_id=None, parent_type=None)
    return WalkResult(module_id=module_id, node_ids=node_ids)
