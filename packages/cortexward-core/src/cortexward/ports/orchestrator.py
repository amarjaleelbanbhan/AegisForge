"""Orchestrator port: drives the agent graph over one analysis run (ADR-0002).

LangGraph is the reference adapter, but its types never appear in the domain
or application layers — everything above this port depends only on
:class:`OrchestratorPort`. The agents themselves (Planner, Scanner, Verifier,
Repair, Reviewer, Coordinator, Memory) and the run state they share are
introduced with the agent framework (Phase 4); this port fixes the shape of
"run an analysis, get findings and patches back" ahead of that work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field

from cortexward.domain import Finding, Patch
from cortexward.ports._base import PortModel


class AnalysisRequest(PortModel):
    """A request to analyze one target."""

    root: Path
    languages: tuple[str, ...] = ()
    config: dict[str, str] = Field(default_factory=dict)


class RunResult(PortModel):
    """The outcome of one orchestrated analysis run."""

    run_id: str
    findings: tuple[Finding, ...]
    patches: tuple[Patch, ...] = ()


@runtime_checkable
class OrchestratorPort(Protocol):
    """Coordinates agents over a single analysis run."""

    def run(self, request: AnalysisRequest) -> RunResult:
        """Execute the full pipeline for ``request`` and return its result."""
        ...
