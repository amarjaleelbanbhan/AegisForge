"""A stable identity key for a `Finding`, for cross-run suppression matching.

Deliberately simple — rule id + primary location + CWE — mirroring the same
pragmatism already documented in `cortexward.scanners.normalize`'s
correlation matcher (no more elaborate fingerprint concept exists elsewhere
in the domain model). Two findings at the same rule/location/CWE across
separate runs collapse to the same fingerprint, which is exactly what "was
this specific issue already triaged" (agent repository memory, MPS §15) or
"is this a known, accepted finding" (a CLI `--baseline` file) both need —
the same identity concept, used by two different callers.
"""

from __future__ import annotations

import hashlib

from cortexward.domain.models import Finding


def fingerprint_for(finding: Finding) -> str:
    location = finding.locations[0] if finding.locations else None
    location_key = (
        f"{location.path}:{location.start_line}" if location is not None else "no-location"
    )
    raw = f"{finding.rule_id}|{location_key}|{finding.cwe}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


__all__ = ["fingerprint_for"]
