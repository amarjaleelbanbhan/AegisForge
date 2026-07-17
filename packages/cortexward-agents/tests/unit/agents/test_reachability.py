"""Unit tests for `cortexward.agents.reachability.is_reachable_from_entrypoint`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from cortexward.agents.reachability import is_reachable_from_entrypoint
from cortexward.domain import SourceLocation
from cortexward.ports import CodeGraph, NodeId, TaintPath

pytestmark = pytest.mark.unit


class _FakeCodeGraph:
    """A `CodeGraph` whose `reachable()`/`nodes_at()`/`entrypoints()` are scripted."""

    language = "python"

    def __init__(
        self,
        *,
        entrypoints: Sequence[NodeId] = (),
        nodes_by_location: Mapping[tuple[str, int], Sequence[NodeId]] | None = None,
        reachable_sinks: Sequence[NodeId] = (),
    ) -> None:
        self._entrypoints = tuple(entrypoints)
        self._nodes_by_location = dict(nodes_by_location or {})
        self._reachable_sinks = set(reachable_sinks)

    def entrypoints(self) -> Sequence[NodeId]:
        return self._entrypoints

    def reachable(self, sources: Sequence[NodeId], sink: NodeId) -> bool:
        return sink in self._reachable_sinks

    def taint(
        self, sources: Sequence[NodeId], sinks: Sequence[NodeId], sanitizers: Sequence[NodeId] = ()
    ) -> Sequence[TaintPath]:
        return ()

    def callers(self, function: NodeId) -> Sequence[NodeId]:
        return ()

    def slice(self, node: NodeId) -> Sequence[NodeId]:
        return ()

    def location_of(self, node: NodeId) -> SourceLocation:
        raise KeyError(node)

    def nodes_at(self, path: str, line: int) -> Sequence[NodeId]:
        return self._nodes_by_location.get((path, line), ())


def _location(path: str = "app.py", line: int = 3) -> SourceLocation:
    return SourceLocation(path=path, start_line=line)


class TestIsReachableFromEntrypoint:
    def test_satisfies_the_code_graph_protocol(self) -> None:
        assert isinstance(_FakeCodeGraph(), CodeGraph)

    def test_no_code_graphs_is_not_reachable(self) -> None:
        assert is_reachable_from_entrypoint([_location()], {}) is False

    def test_no_locations_is_not_reachable(self) -> None:
        graph = _FakeCodeGraph(entrypoints=("ep",))
        assert is_reachable_from_entrypoint([], {"python": graph}) is False

    def test_graph_with_no_entrypoints_is_not_reachable(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=(), nodes_by_location={("app.py", 3): ("n1",)}, reachable_sinks=("n1",)
        )
        assert is_reachable_from_entrypoint([_location()], {"python": graph}) is False

    def test_location_with_no_matching_node_is_not_reachable(self) -> None:
        graph = _FakeCodeGraph(entrypoints=("ep",), nodes_by_location={})
        assert is_reachable_from_entrypoint([_location()], {"python": graph}) is False

    def test_matching_node_not_on_the_cfg_chain_is_not_reachable(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=("ep",), nodes_by_location={("app.py", 3): ("n1",)}, reachable_sinks=()
        )
        assert is_reachable_from_entrypoint([_location()], {"python": graph}) is False

    def test_genuine_proof_is_reachable(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=("ep",), nodes_by_location={("app.py", 3): ("n1",)}, reachable_sinks=("n1",)
        )
        assert is_reachable_from_entrypoint([_location()], {"python": graph}) is True

    def test_checks_every_node_a_location_resolves_to_not_just_the_first(self) -> None:
        # The CFG builder only links statement-level nodes; an inner
        # expression node at the same span is commonly unlinked even though
        # a sibling statement node at the identical location is reachable.
        graph = _FakeCodeGraph(
            entrypoints=("ep",),
            nodes_by_location={("app.py", 3): ("inner_expr", "outer_stmt")},
            reachable_sinks=("outer_stmt",),
        )
        assert is_reachable_from_entrypoint([_location()], {"python": graph}) is True

    def test_checks_every_location_a_finding_carries(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=("ep",),
            nodes_by_location={("other.py", 9): ("n1",)},
            reachable_sinks=("n1",),
        )
        locations = [_location(path="app.py", line=3), _location(path="other.py", line=9)]
        assert is_reachable_from_entrypoint(locations, {"python": graph}) is True

    def test_checks_every_code_graph_given(self) -> None:
        empty_graph = _FakeCodeGraph()
        matching_graph = _FakeCodeGraph(
            entrypoints=("ep",), nodes_by_location={("app.py", 3): ("n1",)}, reachable_sinks=("n1",)
        )
        graphs = {"go": empty_graph, "python": matching_graph}
        assert is_reachable_from_entrypoint([_location()], graphs) is True
