"""Shared control-flow-reachability check over one or more `CodeGraph`s.

Extracted from `VerifierAgent`'s own reachability-evidence logic once
`cortexward.agents.threat_model` needed the identical query — "is this
finding's location reachable from a known entry point?" — without also
needing to build an `Evidence` record around the answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cortexward.domain import SourceLocation
from cortexward.ports import CodeGraph


def is_reachable_from_entrypoint(
    locations: Sequence[SourceLocation], code_graphs: Mapping[str, CodeGraph]
) -> bool:
    """Whether any of `locations` is control-flow reachable from a known entry point.

    A genuine positive-proof query: `True` only on an actual proof. `False`
    means "not proven reachable by this run's heuristics" — never "proven
    unreachable" — since entry-point detection (e.g. the Python
    `LanguageProvider`'s `main()`/`if __name__ == "__main__":` heuristic) is
    deliberately narrow.
    """
    for location in locations:
        for graph in code_graphs.values():
            entrypoints = graph.entrypoints()
            if not entrypoints:
                continue
            nodes = graph.nodes_at(location.path, location.start_line)
            if not nodes:
                continue
            # A source location resolves to several overlapping graph nodes
            # (statement, call, sub-expressions, ...), but the CFG builder
            # only links statement-level nodes into its CFG_NEXT chain -- an
            # inner call/expression node this same line also resolves to is
            # often simply absent from that chain. Check every candidate
            # rather than just the most specific one: reachability is a
            # positive-proof query, so any one of them proving a path is a
            # genuine proof.
            if any(graph.reachable(list(entrypoints), node) for node in nodes):
                return True
    return False


__all__ = ["is_reachable_from_entrypoint"]
