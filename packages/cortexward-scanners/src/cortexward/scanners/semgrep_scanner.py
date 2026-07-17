"""A :class:`~cortexward.ports.ScannerPort` adapter wrapping Semgrep.

Unlike `--config=auto` (Semgrep's own default, which fetches rules from
semgrep.dev and requires network access -- ROADMAP.md documented this as
this adapter's blocker for a long time), this adapter always points
`--config` at `semgrep_rules/`, a small set of rules **authored in this
repository** and bundled with the package. No registry lookup, no login,
no network call of any kind: every rule is a local file, so a scan is
fully offline and fully deterministic, matching this project's
offline-determinism bar the same way every other scanner adapter here
already does.

The bundled rules are deliberately not a re-implementation of what Bandit
already covers (`shell=True`, `eval`, weak crypto, ...) -- they target
patterns Bandit's Python-AST-pattern matching doesn't reach at all:
Server-Side Request Forgery via a Flask request value flowing into an
outbound HTTP call, Flask `render_template_string` server-side template
injection, hard-coded credentials by variable name (a syntactic
complement to `SecretsScanner`'s entropy-based approach -- the two tools
agreeing is a *stronger* signal, not a duplicate one, once correlated by
`cortexward.scanners.correlate`), and JWT signature-verification bypass.
Two of the four (SSRF, template injection) use Semgrep's taint mode,
genuinely tracing a value from a Flask request object to a sink -- a
capability Bandit's plain AST pattern matching doesn't have at all.

Every rule was authored and empirically verified against both a
vulnerable and a semantically-equivalent safe fixture before being
committed (see `tests/unit/scanners/test_semgrep_scanner.py`): each rule
fires on the vulnerable case and stays silent on the safe one, not just
"the YAML parses."
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from collections.abc import Iterable, Sequence
from importlib import resources
from pathlib import Path

from cortexward.domain import EXCLUDED_DIR_NAMES, SourceLocation
from cortexward.ports import RawFinding

_SUBPROCESS_TIMEOUT_SECONDS = 300
"""Matches `BanditScanner`'s own bound: a hung Semgrep process must not
hang a whole scan indefinitely."""

_SEVERITY_MAP: dict[str, str] = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
}


def _rules_dir() -> Path:
    """The bundled, offline rule pack's directory, however the package is installed."""
    return Path(str(resources.files("cortexward.scanners") / "semgrep_rules"))


def _rule_id_from_check_id(check_id: str) -> str:
    """`check_id` for a directory `--config` is the rule's own `id:` prefixed
    with the dotted path Semgrep resolved it through (e.g.
    `packages.cortexward-scanners.....semgrep_rules.cortexward-jwt-...`);
    only the final, dot-separated segment is the rule id this project
    actually assigned it.
    """
    return check_id.rsplit(".", 1)[-1]


def _cwe_from_metadata(metadata: object) -> int | None:
    """Extracts the numeric CWE from this project's own `metadata.cwe`
    convention (`"CWE-798: Use of Hard-coded Credentials"`) -- a field this
    project's own rules populate, not a Semgrep-standard one, so this only
    ever sees the shape the bundled rules produce.
    """
    if not isinstance(metadata, dict):
        return None
    cwe_field = metadata.get("cwe")
    if not isinstance(cwe_field, str) or not cwe_field.startswith("CWE-"):
        return None
    digits = cwe_field[len("CWE-") :].split(":", 1)[0].strip()
    return int(digits) if digits.isdigit() else None


def _location_for(result: dict[str, object], *, root: Path) -> SourceLocation | None:
    path = result.get("path")
    if not isinstance(path, str) or not path:
        return None
    filename = Path(path)
    try:
        relative = filename.relative_to(root)
    except ValueError:
        relative = filename
    start = result.get("start")
    end = result.get("end")
    start_line = start.get("line", 1) if isinstance(start, dict) else 1
    start_col = start.get("col", 1) if isinstance(start, dict) else 1
    end_line = end.get("line", start_line) if isinstance(end, dict) else start_line
    end_col = end.get("col", start_col) if isinstance(end, dict) else start_col
    return SourceLocation(
        path=str(relative),
        start_line=start_line if isinstance(start_line, int) and start_line >= 1 else 1,
        start_col=start_col if isinstance(start_col, int) and start_col >= 1 else 1,
        end_line=end_line if isinstance(end_line, int) and end_line >= 1 else start_line,
        end_col=end_col if isinstance(end_col, int) and end_col >= 1 else start_col,
    )


def _finding_from_result(result: dict[str, object], *, root: Path) -> RawFinding | None:
    check_id = result.get("check_id")
    if not isinstance(check_id, str):
        return None
    location = _location_for(result, root=root)
    if location is None:
        return None
    extra = result.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    message = extra.get("message")
    severity = extra.get("severity")
    return RawFinding(
        rule_id=_rule_id_from_check_id(check_id),
        message=message if isinstance(message, str) else check_id,
        location=location,
        severity_hint=_SEVERITY_MAP.get(severity) if isinstance(severity, str) else None,
        cwe=_cwe_from_metadata(extra.get("metadata")),
        raw={"check_id": check_id},
    )


class SemgrepScanner:
    """Runs the bundled, offline Semgrep rule pack over a Python project."""

    name = "semgrep"

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        if languages and "python" not in languages:
            return
        semgrep = shutil.which("semgrep")
        if semgrep is None:
            # Degrades to no findings, the same as OsvScanner on a network
            # failure or BanditScanner on a timeout -- one missing/broken
            # tool must not crash the whole multi-scanner pipeline.
            return
        resolved_root = root.resolve()
        excludes: list[str] = []
        for excluded in EXCLUDED_DIR_NAMES:
            excludes.extend(["--exclude", excluded])
        try:
            # Fixed argv, no shell, --config points only at this project's
            # own bundled rule files -- never --config=auto, never a
            # registry shorthand (see module docstring: no network access
            # of any kind).
            process = subprocess.run(  # noqa: S603 # nosec B603
                [
                    semgrep,
                    "--config",
                    str(_rules_dir()),
                    "--json",
                    "--quiet",
                    "--disable-version-check",
                    "--metrics",
                    "off",
                    *excludes,
                    str(resolved_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return
        if not process.stdout.strip():
            return
        payload = json.loads(process.stdout)
        for result in payload.get("results", []):
            if not isinstance(result, dict):
                continue
            finding = _finding_from_result(result, root=resolved_root)
            if finding is not None:
                yield finding


__all__ = ["SemgrepScanner"]
