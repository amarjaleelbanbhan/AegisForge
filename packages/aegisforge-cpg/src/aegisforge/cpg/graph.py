"""An in-memory :class:`~aegisforge.ports.code_graph.CodeGraph` implementation.

This is the reference graph engine: language-agnostic, backed by adjacency
lists over the four edge kinds in :mod:`aegisforge.cpg.model`. A
:class:`GraphBuilder` accumulates nodes and edges (as a
:class:`~aegisforge.ports.language_provider.LanguageProvider` walks a parse
tree) and produces a frozen, queryable :class:`InMemoryCodeGraph`.

Reachability and slicing traverse ``CFG_NEXT``/``CALLS``/``DFG_REACHES``
edges — the edges that represent control or data *influence*. ``AST_CHILD``
edges are syntactic containment only and are not traversed by these queries;
callers use them (via ``location_of``/inspection) to navigate structure, not
to reason about flow.

Until a control-flow or data-flow builder populates ``CFG_NEXT`` /
``DFG_REACHES`` edges (later Phase 2 milestones), a graph built from AST
alone correctly reports no control/data paths — the algorithms below are
complete and correct over whatever edges exist; they do not fabricate
results.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence

from aegisforge.cpg.model import Edge, EdgeKind, Node, NodeKind
from aegisforge.domain import SourceLocation
from aegisforge.ports import NodeId, TaintPath

_INFLUENCE_KINDS = (EdgeKind.CFG_NEXT, EdgeKind.CALLS)
_DATA_KINDS = (EdgeKind.DFG_REACHES,)
_SLICE_KINDS = (EdgeKind.CFG_NEXT, EdgeKind.CALLS, EdgeKind.DFG_REACHES)


class GraphBuilder:
    """Accumulates nodes and edges, then produces an :class:`InMemoryCodeGraph`.

    Not thread-safe and not itself a :class:`~aegisforge.ports.code_graph.
    CodeGraph` — it is a construction-time helper only; queries run against
    the frozen graph returned by :meth:`build`.
    """

    def __init__(self, language: str) -> None:
        self._language = language
        self._nodes: dict[NodeId, Node] = {}
        self._edges: list[Edge] = []
        self._entrypoints: set[NodeId] = set()

    def add_node(
        self,
        node_id: NodeId,
        kind: NodeKind,
        location: SourceLocation,
        *,
        properties: dict[str, str] | None = None,
    ) -> NodeId:
        """Add a node, returning its id for convenient chaining."""
        if node_id in self._nodes:
            raise ValueError(f"node {node_id!r} already added")
        self._nodes[node_id] = Node(
            id=node_id,
            kind=kind,
            language=self._language,
            location=location,
            properties=properties or {},
        )
        return node_id

    def add_edge(self, kind: EdgeKind, source: NodeId, target: NodeId) -> None:
        """Add a directed edge. Both endpoints must already be added nodes."""
        for node_id in (source, target):
            if node_id not in self._nodes:
                raise ValueError(f"cannot add edge referencing unknown node {node_id!r}")
        self._edges.append(Edge(kind=kind, source=source, target=target))

    def mark_entrypoint(self, node_id: NodeId) -> None:
        """Mark ``node_id`` as an externally reachable entry point."""
        if node_id not in self._nodes:
            raise ValueError(f"cannot mark unknown node {node_id!r} as an entrypoint")
        self._entrypoints.add(node_id)

    def build(self) -> InMemoryCodeGraph:
        """Freeze the accumulated nodes/edges into a queryable graph."""
        return InMemoryCodeGraph(
            language=self._language,
            nodes=self._nodes,
            edges=tuple(self._edges),
            entrypoints=frozenset(self._entrypoints),
        )


class InMemoryCodeGraph:
    """A frozen, in-memory implementation of the ``CodeGraph`` port.

    Construct via :class:`GraphBuilder`, never directly.
    """

    def __init__(
        self,
        *,
        language: str,
        nodes: dict[NodeId, Node],
        edges: tuple[Edge, ...],
        entrypoints: frozenset[NodeId],
    ) -> None:
        self._language = language
        self._nodes = dict(nodes)
        self._edges = edges
        self._entrypoint_ids = entrypoints
        self._forward: dict[EdgeKind, dict[NodeId, list[NodeId]]] = {}
        self._backward: dict[EdgeKind, dict[NodeId, list[NodeId]]] = {}
        for edge in edges:
            self._forward.setdefault(edge.kind, {}).setdefault(edge.source, []).append(edge.target)
            self._backward.setdefault(edge.kind, {}).setdefault(edge.target, []).append(edge.source)

    @property
    def language(self) -> str:
        return self._language

    def _require(self, node_id: NodeId) -> None:
        if node_id not in self._nodes:
            raise KeyError(f"no such node: {node_id!r}")

    def _neighbors(
        self, node_id: NodeId, kinds: Iterable[EdgeKind], *, reverse: bool = False
    ) -> Iterable[NodeId]:
        table = self._backward if reverse else self._forward
        for kind in kinds:
            yield from table.get(kind, {}).get(node_id, ())

    def entrypoints(self) -> Sequence[NodeId]:
        return tuple(self._entrypoint_ids)

    def reachable(self, sources: Sequence[NodeId], sink: NodeId) -> bool:
        for node_id in (*sources, sink):
            self._require(node_id)
        frontier: deque[NodeId] = deque(sources)
        visited: set[NodeId] = set(sources)
        if sink in visited:
            return True
        while frontier:
            current = frontier.popleft()
            for neighbor in self._neighbors(current, _INFLUENCE_KINDS):
                if neighbor == sink:
                    return True
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)
        return False

    def taint(
        self,
        sources: Sequence[NodeId],
        sinks: Sequence[NodeId],
        sanitizers: Sequence[NodeId] = (),
    ) -> Sequence[TaintPath]:
        for node_id in (*sources, *sinks, *sanitizers):
            self._require(node_id)
        sanitizer_set = set(sanitizers)
        sink_set = set(sinks)
        paths: list[TaintPath] = []
        for source in sources:
            reached = self._shortest_paths_to_any(source, sink_set, _DATA_KINDS)
            for sink, path in reached.items():
                paths.append(
                    TaintPath(
                        source=source,
                        sink=sink,
                        path=tuple(path),
                        sanitized=any(n in sanitizer_set for n in path),
                    )
                )
        return tuple(paths)

    def _shortest_paths_to_any(
        self, start: NodeId, targets: set[NodeId], kinds: Iterable[EdgeKind]
    ) -> dict[NodeId, list[NodeId]]:
        """BFS shortest paths from ``start`` to each reachable node in ``targets``."""
        kinds = tuple(kinds)
        found: dict[NodeId, list[NodeId]] = {}
        if start in targets:
            found[start] = [start]
        visited = {start}
        frontier: deque[list[NodeId]] = deque([[start]])
        remaining = set(targets) - set(found)
        while frontier and remaining:
            path = frontier.popleft()
            current = path[-1]
            for neighbor in self._neighbors(current, kinds):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                new_path = [*path, neighbor]
                if neighbor in remaining:
                    found[neighbor] = new_path
                    remaining.discard(neighbor)
                frontier.append(new_path)
        return found

    def callers(self, function: NodeId) -> Sequence[NodeId]:
        self._require(function)
        return tuple(self._neighbors(function, (EdgeKind.CALLS,), reverse=True))

    def slice(self, node: NodeId) -> Sequence[NodeId]:
        self._require(node)
        visited: set[NodeId] = {node}
        frontier: deque[NodeId] = deque([node])
        while frontier:
            current = frontier.popleft()
            for neighbor in self._neighbors(current, _SLICE_KINDS, reverse=True):
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)
        return tuple(visited)

    def location_of(self, node: NodeId) -> SourceLocation:
        self._require(node)
        return self._nodes[node].location
