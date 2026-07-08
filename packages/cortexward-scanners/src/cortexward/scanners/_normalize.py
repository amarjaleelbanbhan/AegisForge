"""Normalizes `RawFinding` records from one or more scanners into the domain
`Finding` aggregate, with cross-tool correlation (MPS §17.1, ROADMAP Phase 3).

Each `RawFinding` becomes a `Finding` carrying exactly one `Evidence` entry
of kind `STATIC_MATCH` at `VerificationRung.NONE` — "only a raw detection
signal exists" is the ladder's own definition of that rung; nothing here
claims more confidence than a pattern match warrants. Later Verification
Ladder stages (reachability, taint, PoC — later phases) attach further
`Evidence` to the *same* `Finding`, they don't create new ones.

**Correlation** merges findings from different scanners that are very likely
the same real bug: same file, same starting line, same CWE. CWE is the only
identifier used across tools here — different scanners name the same bug
class under different `rule_id`s (Bandit's `B602` vs. a Semgrep rule slug),
so `rule_id` alone can't anchor a cross-tool match, while CWE is a shared,
tool-agnostic vocabulary. A finding with no CWE (or from a scanner, like
`detect-secrets`, that only reports credential exposure, i.e. always the
same CWE-798) is only ever merged with something at the exact same location
sharing that CWE — never guessed at by message text or rule name similarity.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    Provenance,
    Severity,
    VerificationRung,
)
from cortexward.ports import RawFinding

_SEVERITY_BY_HINT: dict[str, Severity] = {
    "info": Severity.INFO,
    "informational": Severity.INFO,
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


def _severity_from_hint(hint: str | None) -> Severity:
    if hint is None:
        return Severity.MEDIUM
    return _SEVERITY_BY_HINT.get(hint.strip().lower(), Severity.MEDIUM)


def normalize(raw: RawFinding, *, producer: str) -> Finding:
    """A single `RawFinding`, normalized into a fresh `Finding`.

    The new `Finding` carries one supporting `STATIC_MATCH` `Evidence` entry
    attributed to `producer` (a `ScannerPort.name`, e.g. `"bandit"`).
    """
    provenance = Provenance(producer=producer)
    evidence = Evidence(
        kind=EvidenceKind.STATIC_MATCH,
        rung=VerificationRung.NONE,
        supports=True,
        summary=raw.message,
        provenance=provenance,
        data=dict(raw.raw),
    )
    return Finding(
        rule_id=raw.rule_id,
        title=f"{producer}: {raw.rule_id}",
        message=raw.message,
        severity=_severity_from_hint(raw.severity_hint),
        cwe=raw.cwe,
        locations=(raw.location,),
        evidence=(evidence,),
        provenance=provenance,
        tags=frozenset({producer}),
    )


_CorrelationKey = tuple[str, int, int]


def _correlation_key(finding: Finding) -> _CorrelationKey | None:
    """A cross-tool identity key for `finding`, or `None` if it can't be
    safely correlated — no CWE means location + rule name alone isn't a
    reliable enough signal that two different tools found the *same* bug.
    """
    if finding.cwe is None or not finding.locations:
        return None
    location = finding.locations[0]
    return (location.path, location.start_line, finding.cwe)


def _merge(primary: Finding, other: Finding) -> Finding:
    """Merges `other` into `primary`: accumulated evidence, worst-case
    severity, every contributing producer's tag, every reported location.
    """
    merged_locations = tuple(dict.fromkeys((*primary.locations, *other.locations)))
    return primary.model_copy(
        update={
            "locations": merged_locations,
            "evidence": (*primary.evidence, *other.evidence),
            "tags": primary.tags | other.tags,
            "severity": max(primary.severity, other.severity),
            "related_ids": primary.related_ids | {other.id},
            "updated_at": datetime.now(UTC),
        }
    )


def correlate(results: Mapping[str, Iterable[RawFinding]]) -> list[Finding]:
    """Normalizes every scanner's raw findings and merges cross-tool matches.

    `results` maps a scanner's `ScannerPort.name` to the `RawFinding`s it
    produced in one run. See the module docstring for the correlation rule.
    """
    merged: dict[_CorrelationKey, Finding] = {}
    unmerged: list[Finding] = []
    for producer, raw_findings in results.items():
        for raw in raw_findings:
            finding = normalize(raw, producer=producer)
            key = _correlation_key(finding)
            if key is None:
                unmerged.append(finding)
                continue
            merged[key] = _merge(merged[key], finding) if key in merged else finding
    return [*merged.values(), *unmerged]
