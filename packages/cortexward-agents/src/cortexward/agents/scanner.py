"""Scanner agent (MPS §13): plan -> raw findings, via configured `ScannerPort` adapters.

Mirrors `cortexward.orchestrator.sequential.SequentialOrchestrator`'s own
scan-then-correlate step as one `Agent` instead of a whole `OrchestratorPort`.
`ScannerPort` instances are injected at construction time (e.g. via
`cortexward.orchestrator.sequential.default_scanners()`), not auto-discovered
here, to keep this package's plugin-discovery surface limited to what it's
actually given.
"""

from __future__ import annotations

from collections.abc import Sequence

from cortexward.agents.state import RunState
from cortexward.ports import RawFinding, ScannerPort
from cortexward.scanners import correlate


class ScannerAgent:
    """Runs every configured `ScannerPort` against the request root and correlates the results."""

    name = "scanner"

    def __init__(self, *, scanners: Sequence[ScannerPort]) -> None:
        self._scanners = tuple(scanners)

    def run(self, state: RunState) -> RunState:
        results: dict[str, list[RawFinding]] = {
            scanner.name: list(scanner.scan(state.request.root, languages=state.request.languages))
            for scanner in self._scanners
        }
        findings = tuple(correlate(results))
        note = (
            f"{len(findings)} finding(s) after correlation across {len(self._scanners)} scanner(s)"
        )
        return state.with_findings(findings).with_note(self.name, note).with_completed(self.name)


__all__ = ["ScannerAgent"]
