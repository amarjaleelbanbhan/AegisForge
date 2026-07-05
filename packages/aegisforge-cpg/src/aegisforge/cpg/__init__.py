"""The AegisForge Code Property Graph engine (MPS §12).

Provides the reference, in-memory implementation of the
:class:`~aegisforge.ports.code_graph.CodeGraph` port: a language-agnostic
node/edge schema (:mod:`aegisforge.cpg.model`) and a builder + query engine
(:mod:`aegisforge.cpg.graph`). Language-specific parsing into this schema
lives in ``aegisforge.languages.*`` (e.g. the Python provider), which depends
on this package rather than the reverse.
"""

from __future__ import annotations

from aegisforge.cpg.graph import GraphBuilder, InMemoryCodeGraph
from aegisforge.cpg.model import Edge, EdgeKind, Node, NodeKind

__all__ = [
    "Edge",
    "EdgeKind",
    "GraphBuilder",
    "InMemoryCodeGraph",
    "Node",
    "NodeKind",
]
