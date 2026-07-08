"""A :class:`~cortexward.ports.ReporterPort` adapter rendering SARIF 2.1.0.

SARIF (Static Analysis Results Interchange Format) is the standard consumed
by GitHub code scanning, most CI dashboards, and IDE integrations. This
module renders CortexWard's internal :class:`~cortexward.domain.Finding`
model into it — an *export* format, never the internal model itself
(ADR-0003): `Finding` stays richer (evidence, verification rung, VEX status,
...) than SARIF's `result` shape can express, so nothing here is a two-way
mapping.

**Scope:** one `run`, one `tool.driver` (CortexWard itself — the tool that
*produced* the SARIF file, not the individual scanners that fed it; those
appear per-finding via `properties.producers`, since a merged/correlated
finding may have more than one). Every distinct `rule_id` across `findings`
becomes one `reportingDescriptor` in `tool.driver.rules`; a `Finding`'s
`locations` become one SARIF `location` each, and `Evidence.summary` entries
are not spelled out individually — SARIF's `result` is a single-message
shape, matching how a Finding is reported here at its current confidence,
not a full evidence trail (that stays in CortexWard's own JSON export,
future work).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from cortexward.core import version as core_version
from cortexward.domain import Finding, Severity, SourceLocation
from cortexward.ports import RenderedArtifact

_SCHEMA_URI = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)
_SARIF_VERSION = "2.1.0"
_TOOL_NAME = "CortexWard"
_INFORMATION_URI = "https://github.com/amarjaleelbanbhan/CortexWard"

_LEVEL_BY_SEVERITY: dict[Severity, str] = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def _level_for(severity: Severity) -> str:
    return _LEVEL_BY_SEVERITY.get(severity, "warning")


def _rule_for(finding: Finding) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": finding.rule_id,
        "shortDescription": {"text": finding.title},
    }
    if finding.cwe is not None:
        rule["properties"] = {"tags": [f"external/cwe/cwe-{finding.cwe}"], "cwe": finding.cwe}
    return rule


def _rules_for(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for finding in findings:
        by_id.setdefault(finding.rule_id, _rule_for(finding))
    return list(by_id.values())


def _location_for(location: SourceLocation) -> dict[str, Any]:
    region: dict[str, Any] = {"startLine": location.start_line, "startColumn": location.start_col}
    if location.end_line is not None:
        region["endLine"] = location.end_line
    if location.end_col is not None:
        region["endColumn"] = location.end_col
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": location.path},
            "region": region,
        }
    }


def _result_for(finding: Finding) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "level": _level_for(finding.severity),
        "message": {"text": finding.message},
        "locations": [_location_for(loc) for loc in finding.locations],
    }
    properties: dict[str, Any] = {"state": finding.state.value}
    if finding.cwe is not None:
        properties["cwe"] = finding.cwe
    if finding.tags:
        properties["producers"] = sorted(finding.tags)
    result["properties"] = properties
    return result


class SarifReporter:
    """Renders a set of `Finding`s into a SARIF 2.1.0 JSON document."""

    format_id = "sarif"

    def render(self, findings: Sequence[Finding]) -> RenderedArtifact:
        document = {
            "$schema": _SCHEMA_URI,
            "version": _SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": _TOOL_NAME,
                            "informationUri": _INFORMATION_URI,
                            "version": core_version(),
                            "rules": _rules_for(findings),
                        }
                    },
                    "results": [_result_for(finding) for finding in findings],
                }
            ],
        }
        content = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            content=content, media_type="application/sarif+json", filename="cortexward.sarif"
        )
