"""A findings baseline: known/accepted findings a scan shouldn't re-flag.

Closes a gap this project's own docs have flagged since Phase 8's CLI first
shipped: `ward scan packages` surfaces real findings in this repo's own
test fixtures (deliberately fake secrets, `subprocess(shell=True)` examples
in scanner-adapter tests) that are true positives *for the pattern*, not
real vulnerabilities — with no suppression mechanism, `ward scan` could
never run clean in `ci.yml`. A baseline file records a finding's
`fingerprint_for()` identity; `ward scan --baseline <file>` excludes any
finding whose fingerprint is listed from both the rendered report and the
`--fail-on` exit-code check, and `ward baseline <path>` generates one from
today's plain scanner findings (no LLM — a baseline records what the
scanners themselves find, not an LLM-influenced verification outcome).

The file format is deliberately simple, matching this codebase's own JSON
reporter conventions rather than inventing a new one:

    {"suppressions": [{"fingerprint": "...", "rule_id": "...", "path": "...",
                        "reason": "..."}]}

`rule_id`/`path` are recorded for human readability only (reviewing a diff
to a baseline file should be legible) — the identity match itself is
`fingerprint` alone.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from cortexward.domain import Finding, fingerprint_for


def load_baseline(path: Path) -> frozenset[str]:
    """Reads the set of accepted fingerprints from a baseline file."""
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document.get("suppressions", [])
    return frozenset(str(entry["fingerprint"]) for entry in entries)


def write_baseline(path: Path, findings: Sequence[Finding], *, reason: str) -> None:
    """Writes every finding's fingerprint to a new baseline file, overwriting `path`."""
    document = {
        "suppressions": [
            {
                "fingerprint": fingerprint_for(finding),
                "rule_id": finding.rule_id,
                "path": finding.locations[0].path if finding.locations else None,
                "reason": reason,
            }
            for finding in findings
        ]
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def filter_baseline(findings: Sequence[Finding], baseline: frozenset[str]) -> tuple[Finding, ...]:
    """Every finding in `findings` whose fingerprint isn't in `baseline`."""
    return tuple(finding for finding in findings if fingerprint_for(finding) not in baseline)


__all__ = ["filter_baseline", "load_baseline", "write_baseline"]
