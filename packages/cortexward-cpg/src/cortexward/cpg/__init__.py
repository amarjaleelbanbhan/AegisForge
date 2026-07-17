"""The CortexWard Code Property Graph engine (MPS §12).

Provides the reference, in-memory implementation of the
:class:`~cortexward.ports.code_graph.CodeGraph` port: a language-agnostic
node/edge schema (:mod:`cortexward.cpg.model`) and a builder + query engine
(:mod:`cortexward.cpg.graph`). Language-specific parsing into this schema
lives in ``cortexward.languages.*`` (e.g. the Python provider), which depends
on this package rather than the reverse.
"""

from __future__ import annotations

from cortexward.cpg.graph import GraphBuilder, InMemoryCodeGraph
from cortexward.cpg.model import Edge, EdgeKind, Node, NodeKind

__all__ = [
    "Edge",
    "EdgeKind",
    "GraphBuilder",
    "InMemoryCodeGraph",
    "Node",
    "NodeKind",
]
