"""Builds a `ThreatModel` for one scan target (MPS Phase 5, MPS §13).

Mirrors `build_pipeline`'s role: every delivery surface that wants a threat
model needs the same "scan, optionally build a `CodeGraph`, classify under
STRIDE" sequence, so it's written once here — this is the one place
`cortexward-orchestrator` depends on `cortexward.agents.threat_model` /
`cortexward.agents.build_code_graphs`, for the same reason `pipeline.py`
depends on `cortexward.agents` for `AgentOrchestrator`.

Deliberately always scanner-only (no LLM parameter): STRIDE classification
and reachability are both deterministic, so a threat model doesn't need —
and this function never triggers — the agent-driven pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from cortexward.agents import build_code_graphs
from cortexward.agents import build_threat_model as _build_threat_model
from cortexward.domain import ThreatModel
from cortexward.orchestrator.sequential import SequentialOrchestrator, default_scanners
from cortexward.ports import AnalysisRequest


def build_threat_model_for(
    *, root: Path, languages: Sequence[str] = (), reachability: bool = True
) -> ThreatModel:
    """Scans `root` and returns a STRIDE-categorized `ThreatModel` over the findings."""
    orchestrator = SequentialOrchestrator(scanners=default_scanners())
    result = orchestrator.run(AnalysisRequest(root=root, languages=tuple(languages)))
    code_graphs = build_code_graphs(root, languages=languages) if reachability else None
    return _build_threat_model(result.findings, code_graphs)


__all__ = ["build_threat_model_for"]
