"""CodeGraph port: the queryable Code Property Graph (MPS §12, §17.1).

A :class:`CodeGraph` is what a :class:`~aegisforge.ports.language_provider.
LanguageProvider` produces by parsing one analysis target. It unifies AST,
control-flow, data-flow, and call-graph edges behind a query API used by
reachability and taint analysis (Verification Ladder rungs 1-2) and by
LLM-grounded retrieval. Concrete graphs (in-memory, or a graph-store-backed
implementation for large repos) are adapters implementing this contract;
nothing in the core depends on a specific graph engine.

Nodes are addressed by an opaque :data:`NodeId` rather than a rich object so
the port stays engine-agnostic; callers resolve a node's source location via
:meth:`CodeGraph.location_of`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from aegisforge.domain import SourceLocation
from aegisforge.ports._base import PortModel

NodeId = str
"""An opaque, graph-local identifier for a CPG node."""


class TaintPath(PortModel):
    """A single data-flow path discovered by :meth:`CodeGraph.taint`."""

    source: NodeId
    sink: NodeId
    path: tuple[NodeId, ...]
    sanitized: bool = False
    """True if a declared sanitizer lies on this path (the flow is blocked)."""


@runtime_checkable
class CodeGraph(Protocol):
    """A parsed Code Property Graph for one analysis target.

    Implementations MUST be built from parsing and manifest reading only —
    never by executing code under the analyzed tree (ADR-0004).
    """

    @property
    def language(self) -> str:
        """The language this graph was parsed for, e.g. ``"python"``."""
        ...

    def entrypoints(self) -> Sequence[NodeId]:
        """Nodes considered externally reachable entry points."""
        ...

    def reachable(self, sources: Sequence[NodeId], sink: NodeId) -> bool:
        """Whether ``sink`` is control-flow reachable from any of ``sources``."""
        ...

    def taint(
        self,
        sources: Sequence[NodeId],
        sinks: Sequence[NodeId],
        sanitizers: Sequence[NodeId] = (),
    ) -> Sequence[TaintPath]:
        """Data-flow paths from ``sources`` to ``sinks``.

        Paths passing through a node in ``sanitizers`` are still returned but
        marked ``sanitized=True``, so callers can decide how to score them.
        """
        ...

    def callers(self, function: NodeId) -> Sequence[NodeId]:
        """Direct call sites of ``function``."""
        ...

    def slice(self, node: NodeId) -> Sequence[NodeId]:
        """A program slice: nodes that can influence ``node``'s value."""
        ...

    def location_of(self, node: NodeId) -> SourceLocation:
        """The source location a graph node corresponds to."""
        ...
