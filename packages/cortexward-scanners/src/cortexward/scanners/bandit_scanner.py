"""A :class:`~cortexward.ports.ScannerPort` adapter wrapping Bandit.

Bandit is a static analyzer: it parses Python source with the standard
library `ast` module and never executes it, so shelling out to it does not
violate the non-execution guarantee (ADR-0004) — that guarantee is about
*analyzed project* code, not about running well-understood, trusted
third-party analysis tools.

Invoked via ``python -m bandit`` (not the ``bandit`` console script) so
resolution doesn't depend on the interpreter's ``PATH``, and with ``-f json``
for a stable, structured result format. A finding-free run and a
findings-found run both exit non-zero-or-zero depending on Bandit's own
policy — the JSON payload, not the exit code, is what's authoritative here.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from cortexward.domain import EXCLUDED_DIR_NAMES, SourceLocation
from cortexward.ports import RawFinding

_SUBPROCESS_TIMEOUT_SECONDS = 300
"""Generous but bounded: a hung Bandit process must not hang a whole scan
indefinitely, matching every network call in this codebase already having
an explicit timeout (`OsvScanner`, every `LLMPort` adapter)."""


def _int(value: object, *, default: int) -> int:
    """`value` as an `int` if it genuinely is one, else `default`.

    Bandit's JSON schema isn't a versioned contract this codebase controls;
    treating its numeric fields as untrusted (ADR-0004) means never letting
    a surprising type crash the whole scan.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _raw_fields(result: dict[str, object]) -> dict[str, str]:
    """Bandit's own result fields, preserved as strings for audit/debugging."""
    fields: dict[str, str] = {}
    for key in ("test_name", "issue_confidence", "more_info", "col_offset", "end_col_offset"):
        value = result.get(key)
        if value is not None:
            fields[key] = str(value)
    line_range = result.get("line_range")
    if isinstance(line_range, list):
        fields["line_range"] = ",".join(str(n) for n in line_range)
    return fields


def _location_for(result: dict[str, object], *, root: Path) -> SourceLocation:
    filename = Path(str(result["filename"]))
    try:
        relative = filename.relative_to(root)
    except ValueError:
        relative = filename
    start_line = _int(result.get("line_number"), default=1)
    line_range = result.get("line_range")
    end_line = (
        _int(line_range[-1], default=start_line)
        if isinstance(line_range, list) and line_range
        else start_line
    )
    return SourceLocation(
        path=str(relative),
        start_line=start_line,
        start_col=_int(result.get("col_offset"), default=0) + 1,
        end_line=end_line,
        end_col=_int(result.get("end_col_offset"), default=0) + 1,
    )


def _cwe_for(result: dict[str, object]) -> int | None:
    cwe = result.get("issue_cwe")
    if isinstance(cwe, dict):
        cwe_id = cwe.get("id")
        if isinstance(cwe_id, int) and not isinstance(cwe_id, bool):
            return cwe_id
    return None


def _finding_from_result(result: dict[str, object], *, root: Path) -> RawFinding:
    return RawFinding(
        rule_id=str(result["test_id"]),
        message=str(result["issue_text"]),
        location=_location_for(result, root=root),
        severity_hint=str(result["issue_severity"]) if result.get("issue_severity") else None,
        cwe=_cwe_for(result),
        raw=_raw_fields(result),
    )


class BanditScanner:
    """Runs Bandit over a Python project and yields its findings as `RawFinding`."""

    name = "bandit"

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        if languages and "python" not in languages:
            return
        resolved_root = root.resolve()
        excludes = ",".join(f"*/{name}/*" for name in EXCLUDED_DIR_NAMES)
        try:
            # Fixed argv, no shell, trusted tool (see module docstring).
            process = subprocess.run(  # noqa: S603 # nosec B603
                [
                    sys.executable,
                    "-m",
                    "bandit",
                    "-f",
                    "json",
                    "-q",
                    "-r",
                    str(resolved_root),
                    "-x",
                    excludes,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            # Degrades to no findings from this scanner, same as OsvScanner
            # on a network failure -- one hung tool must not crash the whole
            # multi-scanner pipeline.
            return
        if not process.stdout.strip():
            return
        payload = json.loads(process.stdout)
        for result in payload.get("results", []):
            yield _finding_from_result(result, root=resolved_root)
