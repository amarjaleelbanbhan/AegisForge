"""A sequential, in-process `OrchestratorPort` implementation (MPS §13, ADR-0002).

Runs every configured `ScannerPort`'s `scan()` in sequence, then normalizes
and correlates the results into `Finding`s via `cortexward.scanners.
correlate`. This is the reference in-process orchestrator: no LLM, no
agents, no planning — exactly "run every scanner and merge the results,"
which every later Phase 4 capability (agent-driven planning, verification,
repair) builds on top of rather than replaces.

`default_scanners()` auto-discovers every scanner registered under the
`cortexward.scanners` entry-point group, so wiring a new scanner package
into an orchestrator run needs zero changes here — the same
zero-core-changes plugin discovery every other adapter family already uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import uuid4

from cortexward.plugins import PluginGroup, registry_for
from cortexward.ports import AnalysisRequest, RawFinding, RunResult, ScannerPort
from cortexward.scanners import correlate


class SequentialOrchestrator:
    """Runs every configured scanner in sequence and correlates the results."""

    def __init__(self, *, scanners: Sequence[ScannerPort]) -> None:
        self._scanners = tuple(scanners)

    def run(self, request: AnalysisRequest) -> RunResult:
        results: dict[str, list[RawFinding]] = {
            scanner.name: list(scanner.scan(request.root, languages=request.languages))
            for scanner in self._scanners
        }
        findings = correlate(results)
        return RunResult(run_id=f"run_{uuid4().hex[:16]}", findings=tuple(findings))


def default_scanners() -> tuple[ScannerPort, ...]:
    """Instantiates every scanner registered under the `cortexward.scanners`
    entry-point group, with no static import of any concrete scanner package."""
    registry = registry_for(PluginGroup.SCANNERS)
    return tuple(cast("ScannerPort", registry.create(name)) for name in registry.available())
