"""Builds a `ThreatModel` from scanner findings (MPS Phase 5).

Deliberately not an `Agent`: STRIDE classification is a pure CWE lookup
(`cortexward.domain.threat_model.stride_categories_for`) and reachability is
a deterministic graph query (`cortexward.agents.reachability`) — neither
needs an LLM, so this stays usable from a plain scanner pipeline exactly the
way `cortexward.cli.baseline` does, not gated behind `--llm-provider`.

A finding becomes a `Threat` only when its CWE resolves to at least one
STRIDE category; a finding with no CWE, or a CWE this project has no
confident STRIDE mapping for, contributes nothing rather than being forced
into a category with no basis (see `stride_categories_for`'s docstring).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cortexward.agents.reachability import crosses_trust_boundary, is_reachable_from_entrypoint
from cortexward.domain import Finding, Threat, ThreatModel, stride_categories_for
from cortexward.ports import CodeGraph


def _threat_for(finding: Finding, *, code_graphs: Mapping[str, CodeGraph]) -> Threat | None:
    categories = stride_categories_for(finding.cwe)
    if not categories or finding.cwe is None:
        return None
    return Threat(
        finding_id=finding.id,
        rule_id=finding.rule_id,
        cwe=finding.cwe,
        categories=categories,
        severity=finding.severity,
        location=finding.locations[0] if finding.locations else None,
        reachable_from_entrypoint=is_reachable_from_entrypoint(finding.locations, code_graphs),
        crosses_trust_boundary=crosses_trust_boundary(finding.locations, code_graphs),
    )


def build_threat_model(
    findings: Sequence[Finding], code_graphs: Mapping[str, CodeGraph] | None = None
) -> ThreatModel:
    """A STRIDE-categorized `ThreatModel` over `findings`.

    `code_graphs` (from `cortexward.agents.code_graphs.build_code_graphs`) is
    optional: without one, every `Threat.reachable_from_entrypoint` is
    `False` — "not proven," the same honest default a run with no usable
    code graph gets everywhere else in this framework, never a guess.
    """
    graphs = code_graphs or {}
    threats = tuple(
        threat
        for finding in findings
        if (threat := _threat_for(finding, code_graphs=graphs)) is not None
    )
    return ThreatModel(threats=threats)


__all__ = ["build_threat_model"]
