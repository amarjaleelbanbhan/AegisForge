"""Populates DFG_REACHES edges via reaching-definitions dataflow analysis.

Runs as a third pass over the same tree-sitter tree, reusing the CFG_NEXT
edges the control-flow builder already produced (see
``_cfg_builder.build_control_flow``'s return value) to run a standard
iterative reaching-definitions analysis:

    IN[n]  = union of OUT[pred] for every CFG predecessor pred of n
    OUT[n] = GEN[n] | (IN[n] - KILL[n])

where ``GEN[n]`` is the set of (variable, defining-node) pairs a statement
defines, and ``KILL[n]`` removes any other definition of the same variable
name. For each *use* of a variable at a node, every definition in that
node's ``IN`` set with a matching name becomes a ``DFG_REACHES`` edge from
the definition to the use.

**Scope of this pass:** plain-identifier assignment (``x = ...``),
augmented assignment (``x += ...``, read-then-write), ``for``-loop targets,
and function parameters, as definitions; any bare identifier reference
(excluding attribute-name and keyword-argument-name positions, which are not
variable references) as a use.

**Explicitly out of scope:** destructuring targets (tuple/list unpacking),
attribute/subscript assignment targets (``self.x = 1``, ``d[k] = 1``) as
definitions of a new name, ``with``-``as`` bindings as definitions, and
names bound by ``import``. These identifiers are still visited as *uses* of
whatever they reference (e.g. ``self`` in ``self.x = 1``), so nothing
crashes or goes unclassified — they just do not yet produce reaching
definitions of their own. Each is a natural, separately scoped extension.
"""

from __future__ import annotations

from tree_sitter import Node as TSNode

from cortexward.cpg import EdgeKind, GraphBuilder
from cortexward.languages.python._ast_walker import TSNodeKey, ts_node_key
from cortexward.ports import NodeId

Definition = tuple[str, NodeId]
"""A (variable name, defining-or-using node id) pair."""

_CONDITION_TS_TYPES = frozenset({"if_statement", "elif_clause", "while_statement"})
_NON_RECURSE_CHILD_TYPES = frozenset({"block"})


def _text(node: TSNode, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _collect_uses(
    node: TSNode, *, node_ids: dict[TSNodeKey, NodeId], source: bytes, out: list[Definition]
) -> None:
    """Recursively collect variable-reference identifiers under `node` as uses."""
    if node.type == "identifier":
        out.append((_text(node, source), node_ids[ts_node_key(node)]))
        return
    if node.type == "attribute":
        # `obj.attr`: only `obj` is a variable reference; `attr` is a member name.
        obj = node.child_by_field_name("object")
        if obj is not None:
            _collect_uses(obj, node_ids=node_ids, source=source, out=out)
        return
    if node.type == "keyword_argument":
        # `name=value` in a call: `name` is not a variable reference.
        value = node.child_by_field_name("value")
        if value is not None:
            _collect_uses(value, node_ids=node_ids, source=source, out=out)
        return
    for child in node.named_children:
        _collect_uses(child, node_ids=node_ids, source=source, out=out)


def _extract_plain_assignment(
    stmt: TSNode, *, node_ids: dict[TSNodeKey, NodeId], source: bytes
) -> tuple[list[Definition], list[Definition]]:
    """`assignment` / `for_statement`: `left = right`-shaped def(+use)."""
    defs: list[Definition] = []
    uses: list[Definition] = []
    left = stmt.child_by_field_name("left")
    right = stmt.child_by_field_name("right")
    if left is not None:
        if left.type == "identifier":
            defs.append((_text(left, source), node_ids[ts_node_key(left)]))
        else:
            _collect_uses(left, node_ids=node_ids, source=source, out=uses)
    if right is not None:
        _collect_uses(right, node_ids=node_ids, source=source, out=uses)
    return defs, uses


def _extract_augmented_assignment(
    stmt: TSNode, *, node_ids: dict[TSNodeKey, NodeId], source: bytes
) -> tuple[list[Definition], list[Definition]]:
    """`augmented_assignment` (`x += ...`): reads then redefines the target."""
    defs: list[Definition] = []
    uses: list[Definition] = []
    left = stmt.child_by_field_name("left")
    right = stmt.child_by_field_name("right")
    if left is not None:
        if left.type == "identifier":
            name, left_id = _text(left, source), node_ids[ts_node_key(left)]
            uses.append((name, left_id))  # reads the current value
            defs.append((name, left_id))  # then redefines it
        else:
            _collect_uses(left, node_ids=node_ids, source=source, out=uses)
    if right is not None:
        _collect_uses(right, node_ids=node_ids, source=source, out=uses)
    return defs, uses


def _unwrap_expression_statement(stmt: TSNode) -> TSNode:
    """An `expression_statement` wrapping one expression (e.g. `x = 1`'s
    `assignment`, or a bare call for its side effects) is unwrapped so
    dispatch below sees the real expression, not a generic wrapper. The
    `expression_statement`'s own node id remains the program point either
    way — only the *dispatch decision* uses the unwrapped node.
    """
    if stmt.type == "expression_statement" and stmt.named_child_count == 1:
        return stmt.named_children[0]
    return stmt


def _extract_defs_uses(
    stmt: TSNode, *, node_ids: dict[TSNodeKey, NodeId], source: bytes
) -> tuple[list[Definition], list[Definition]]:
    """The defs/uses a single statement contributes at its own level.

    Deliberately does not recurse into nested statement lists (`block`
    fields) — those are separate program points, visited independently by
    the scope walker below.
    """
    inner = _unwrap_expression_statement(stmt)
    if inner.type in ("assignment", "for_statement"):
        return _extract_plain_assignment(inner, node_ids=node_ids, source=source)
    if inner.type == "augmented_assignment":
        return _extract_augmented_assignment(inner, node_ids=node_ids, source=source)

    uses: list[Definition] = []
    if inner.type in _CONDITION_TS_TYPES:
        condition = inner.child_by_field_name("condition")
        if condition is not None:
            _collect_uses(condition, node_ids=node_ids, source=source, out=uses)
    elif inner.type not in ("break_statement", "continue_statement", "pass_statement"):
        # Generic fallback: whatever expression(s) this statement wraps are
        # all uses (return's value, with's context managers, a bare
        # expression_statement's call, ...), excluding nested statement lists.
        for child in inner.named_children:
            if child.type not in _NON_RECURSE_CHILD_TYPES:
                _collect_uses(child, node_ids=node_ids, source=source, out=uses)

    return [], uses


def _parameter_defs(
    function_node: TSNode, *, node_ids: dict[TSNodeKey, NodeId], source: bytes
) -> list[Definition]:
    params = function_node.child_by_field_name("parameters")
    if params is None:
        return []
    defs: list[Definition] = []
    for param in params.named_children:
        target = param if param.type == "identifier" else param.child_by_field_name("name")
        if target is not None and target.type == "identifier":
            defs.append((_text(target, source), node_ids[ts_node_key(target)]))
    return defs


class _DataFlowCollector:
    """Walks the same scope structure as `_cfg_builder`, collecting each
    program point's local defs/uses (see `_extract_defs_uses`)."""

    def __init__(self, *, node_ids: dict[TSNodeKey, NodeId], source: bytes) -> None:
        self._node_ids = node_ids
        self._source = source
        self.program_points: dict[NodeId, tuple[list[Definition], list[Definition]]] = {}
        self.entry_seeds: dict[NodeId, list[Definition]] = {}
        """Extra reaching-definitions available at a node's *entry* (IN),
        independent of CFG predecessors — used for function parameters,
        which are bound before the body runs even though no CFG_NEXT edge
        connects the `def` statement to its own body (see
        `_visit_scope_definition`). Seeding IN rather than GEN matters: it
        makes the parameter available to the entry statement's *own* uses
        too, not only to statements after it.
        """

    def run(self, tree_root: TSNode) -> None:
        self._walk_scope(list(tree_root.named_children))

    def _id_of(self, ts_node: TSNode) -> NodeId:
        return self._node_ids[ts_node_key(ts_node)]

    def _walk_scope(self, statements: list[TSNode]) -> None:
        for stmt in statements:
            self._visit_statement(stmt)

    def _visit_statement(self, stmt: TSNode) -> None:
        if stmt.type in ("function_definition", "class_definition"):
            self._visit_scope_definition(stmt)
            return
        if stmt.type == "if_statement":
            self._visit_if_like(stmt)
            return
        if stmt.type in ("while_statement", "for_statement", "with_statement"):
            self._record(stmt)
            body = stmt.child_by_field_name("body")
            if body is not None:
                self._walk_scope(list(body.named_children))
            alternative = stmt.child_by_field_name("alternative")
            self._walk_else(alternative)
            return
        # A leaf program point: assignment, return, break, continue, a bare
        # expression_statement, import, try_statement (atomic — see module
        # docstring), pass, ...
        self._record(stmt)

    def _visit_scope_definition(self, stmt: TSNode) -> None:
        """A nested `def`/`class`: its body is an independent CFG scope with
        no CFG_NEXT predecessor (a function is entered via a call, not by
        falling through its own `def` statement — see `_cfg_builder`), so
        reaching-definitions can't propagate parameters into the body via
        the normal predecessor walk. Instead, parameter defs seed the body's
        first statement's *entry* set directly (see `entry_seeds`).
        """
        body = stmt.child_by_field_name("body")
        if body is None:
            return
        statements = list(body.named_children)
        self._walk_scope(statements)
        if stmt.type == "function_definition" and statements:
            params = _parameter_defs(stmt, node_ids=self._node_ids, source=self._source)
            if params:
                self.entry_seeds[self._id_of(statements[0])] = params

    def _visit_if_like(self, node: TSNode) -> None:
        self._record(node)
        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            self._walk_scope(list(consequence.named_children))
        alternatives = [
            node.children[i]
            for i in range(node.child_count)
            if node.field_name_for_child(i) == "alternative"
        ]
        for alternative in alternatives:
            if alternative.type == "elif_clause":
                self._visit_if_like(alternative)
            else:
                self._walk_else(alternative)

    def _walk_else(self, alternative: TSNode | None) -> None:
        if alternative is None or alternative.type != "else_clause":
            return
        body = alternative.child_by_field_name("body")
        if body is not None:
            self._walk_scope(list(body.named_children))

    def _record(self, stmt: TSNode) -> None:
        self.program_points[self._id_of(stmt)] = _extract_defs_uses(
            stmt, node_ids=self._node_ids, source=self._source
        )


def _reaching_definitions(
    program_points: dict[NodeId, tuple[list[Definition], list[Definition]]],
    cfg_edges: list[tuple[NodeId, NodeId]],
    entry_seeds: dict[NodeId, list[Definition]],
) -> dict[NodeId, set[Definition]]:
    """Standard iterative reaching-definitions dataflow analysis.

    `entry_seeds` adds extra definitions directly into a node's IN set,
    independent of CFG predecessors — see `_DataFlowCollector.entry_seeds`.
    """
    predecessors: dict[NodeId, list[NodeId]] = {}
    for source, target in cfg_edges:
        predecessors.setdefault(target, []).append(source)

    gen: dict[NodeId, set[Definition]] = {}
    kill_names: dict[NodeId, set[str]] = {}
    for node_id, (defs, _uses) in program_points.items():
        gen[node_id] = set(defs)
        kill_names[node_id] = {name for name, _def_id in defs}

    in_sets: dict[NodeId, set[Definition]] = {node_id: set() for node_id in program_points}
    out_sets: dict[NodeId, set[Definition]] = {node_id: set() for node_id in program_points}

    changed = True
    while changed:
        changed = False
        for node_id in program_points:
            new_in: set[Definition] = set(entry_seeds.get(node_id, ()))
            for pred in predecessors.get(node_id, ()):
                new_in |= out_sets.get(pred, set())
            killed = kill_names[node_id]
            survivors = {d for d in new_in if d[0] not in killed}
            new_out = gen[node_id] | survivors
            if new_in != in_sets[node_id] or new_out != out_sets[node_id]:
                in_sets[node_id] = new_in
                out_sets[node_id] = new_out
                changed = True

    return in_sets


def build_data_flow(
    tree_root: TSNode,
    *,
    node_ids: dict[TSNodeKey, NodeId],
    cfg_edges: list[tuple[NodeId, NodeId]],
    source: bytes,
    builder: GraphBuilder,
) -> None:
    """Populate DFG_REACHES edges for every scope in `tree_root`.

    Requires the CFG_NEXT edges `build_control_flow` already produced (for
    the same tree and `node_ids`) to compute reaching definitions.
    """
    collector = _DataFlowCollector(node_ids=node_ids, source=source)
    collector.run(tree_root)
    reaching = _reaching_definitions(collector.program_points, cfg_edges, collector.entry_seeds)

    for node_id, (_defs, uses) in collector.program_points.items():
        reaching_here = reaching[node_id]
        for name, use_id in uses:
            for def_name, def_id in reaching_here:
                if def_name == name:
                    builder.add_edge(EdgeKind.DFG_REACHES, def_id, use_id)
