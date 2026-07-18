"""A :class:`~cortexward.ports.ReporterPort` adapter rendering CycloneDX VEX.

VEX (Vulnerability Exploitability eXchange) answers "is this actually
exploitable in context?" — exactly the question the Verification Ladder
(:mod:`cortexward.domain.verification`) resolves. This module renders that
answer as a CycloneDX 1.5 VEX document (MPS FR-7: "CycloneDX-VEX/CSAF-VEX").
CycloneDX is chosen over CSAF here because its ``analysis.state`` enum maps
directly onto :class:`~cortexward.domain.enums.VexStatus` (both describe one
vulnerability's exploitability); CSAF's document/product_tree scaffold needs
a product/component model this project has no data for outside a full SBOM
run, which is out of scope for a findings-only reporter.

Each `Finding`'s :class:`~cortexward.domain.value_objects.Assessment` is
recomputed here via :func:`cortexward.domain.verification.assess` rather than
read off a stored field — `Assessment` is deliberately a derived view, never
persisted state (see that module's own docstring), so a reporter is exactly
where it belongs to be computed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from cortexward.core import version as core_version
from cortexward.domain import Finding, Severity, VexStatus
from cortexward.domain.verification import assess
from cortexward.ports import RenderedArtifact

_BOM_FORMAT = "CycloneDX"
_SPEC_VERSION = "1.5"
_TOOL_NAME = "CortexWard"

# CycloneDX's `analysis.state` enum has no direct "affected"/"under
# investigation" pair the way VexStatus does — this is the documented,
# one-directional translation from CortexWard's own vocabulary to
# CycloneDX's, not a lossless round-trip.
_ANALYSIS_STATE_BY_VEX_STATUS: dict[VexStatus, str] = {
    VexStatus.NOT_AFFECTED: "not_affected",
    VexStatus.AFFECTED: "exploitable",
    VexStatus.FIXED: "resolved",
    VexStatus.UNDER_INVESTIGATION: "in_triage",
}

_RATING_SEVERITY_BY_SEVERITY: dict[Severity, str] = {
    Severity.INFO: "info",
    Severity.LOW: "low",
    Severity.MEDIUM: "medium",
    Severity.HIGH: "high",
    Severity.CRITICAL: "critical",
}


def _vulnerability_for(finding: Finding) -> dict[str, Any]:
    assessment = assess(finding)
    vulnerability: dict[str, Any] = {
        "bom-ref": f"vex-{finding.id}",
        "id": finding.rule_id,
        "source": {"name": _TOOL_NAME},
        "description": finding.message,
        "ratings": [
            {
                "source": {"name": _TOOL_NAME},
                "severity": _RATING_SEVERITY_BY_SEVERITY[finding.severity],
            }
        ],
        "analysis": {
            "state": _ANALYSIS_STATE_BY_VEX_STATUS[assessment.vex_status],
            "detail": "; ".join(assessment.rationale),
        },
        "affects": [{"ref": f"cortexward:{location.path}"} for location in finding.locations],
    }
    if finding.cwe is not None:
        vulnerability["cwes"] = [finding.cwe]
    return vulnerability


class CycloneDxVexReporter:
    """Renders a set of `Finding`s into a CycloneDX 1.5 VEX JSON document."""

    format_id = "cyclonedx-vex"

    def render(self, findings: Sequence[Finding]) -> RenderedArtifact:
        document = {
            "bomFormat": _BOM_FORMAT,
            "specVersion": _SPEC_VERSION,
            "version": 1,
            "metadata": {
                "tools": [{"vendor": _TOOL_NAME, "name": _TOOL_NAME, "version": core_version()}]
            },
            "vulnerabilities": [_vulnerability_for(finding) for finding in findings],
        }
        content = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            content=content,
            media_type="application/vnd.cyclonedx+json",
            filename="cortexward.vex.json",
        )
