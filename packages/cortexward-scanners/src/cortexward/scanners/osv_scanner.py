"""A :class:`~cortexward.ports.ScannerPort` adapter querying OSV.dev for
known vulnerabilities in exactly-pinned Python dependencies (MPS §17.1).

**Scope decision: exact version pins only** (`==X.Y.Z` in a
`requirements*.txt` line or a PEP 621 `dependencies` entry in
`pyproject.toml`). A range constraint (`>=2.0`, `~=2.0`) doesn't tell us
which version is actually installed; querying OSV without an exact version
returns *every* vulnerability ever recorded for that package name, including
ones long since fixed in whatever version is actually used — a poor-quality,
high-false-positive signal this scanner deliberately does not produce.
Unpinned dependencies are simply skipped, not guessed at.

This scanner does its own minimal pin extraction rather than depending on
`cortexward-cpg`'s `parse_dependencies` — the "Scanner adapters do not
depend on other adapters or interfaces" import-linter contract keeps every
adapter family independent, and this scanner only needs name+exact-version
pairs, not the full `Dependency` record (runtime/dev/optional kind is
irrelevant here: a vulnerable dependency is a vulnerable dependency either
way). Pipfile's exact-pin syntax is out of scope for the same reason
`requirements.txt`/`pyproject.toml` were chosen: they're the two formats
with an unambiguous, easily-isolated `==` exact-pin grammar.

**Network dependency, by design.** Unlike the SAST/secrets adapters, a
vulnerability database query is *supposed* to reflect the current threat
landscape — freshness is the point, not a compromise on this project's
otherwise offline-deterministic bar (contrast the Semgrep-adapter deferral,
where changing *rules* over time would hurt reproducible benchmarking).
Queries go to the public, unauthenticated OSV.dev API over `urllib`
(stdlib) rather than adding an HTTP client dependency for one adapter.
Network failure degrades to no findings, not a crash — one unreachable
service must not abort the rest of a scan.
"""

from __future__ import annotations

import json
import re
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from pathlib import Path

from cortexward.domain import SourceLocation
from cortexward.ports import RawFinding

_OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
_OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{id}"
_ECOSYSTEM = "PyPI"
_REQUEST_TIMEOUT_SECONDS = 15

_EXACT_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([A-Za-z0-9.\-+]+)\s*$")

_Pin = tuple[str, str]
"""(package name, exact version)."""


def _pins_from_requirements_txt(path: Path) -> list[_Pin]:
    pins: list[_Pin] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw_line.split("#", 1)[0].strip()
        match = _EXACT_PIN.match(stripped)
        if match is not None:
            pins.append((match.group(1), match.group(2)))
    return pins


def _pins_from_pyproject_toml(path: Path) -> list[_Pin]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    pins: list[_Pin] = []
    for entry in dependencies:
        if not isinstance(entry, str):
            continue
        match = _EXACT_PIN.match(entry.strip())
        if match is not None:
            pins.append((match.group(1), match.group(2)))
    return pins


def _find_pins(root: Path) -> dict[_Pin, str]:
    """Every exact pin under `root`, mapped to the manifest filename it came
    from. Deduplicated: the same (name, version) declared in two manifests
    is queried once."""
    pins: dict[_Pin, str] = {}
    for candidate in ("requirements.txt", "requirements-dev.txt"):
        path = root / candidate
        if path.is_file():
            for pin in _pins_from_requirements_txt(path):
                pins.setdefault(pin, candidate)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        for pin in _pins_from_pyproject_toml(pyproject):
            pins.setdefault(pin, "pyproject.toml")
    return pins


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    # Fixed https:// URL constants from this module only, never user input.
    request = urllib.request.Request(  # noqa: S310 # nosec B310
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
        return dict(json.loads(response.read()))


def _get_json(url: str) -> dict[str, object]:
    # Fixed https:// URL constants from this module only, never user input.
    with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
        return dict(json.loads(response.read()))


def _query_vulnerable_ids(pins: Sequence[_Pin]) -> list[list[str]]:
    """One vulnerability-id list per pin, in the same order as `pins`."""
    queries = [
        {"package": {"name": name, "ecosystem": _ECOSYSTEM}, "version": version}
        for name, version in pins
    ]
    response = _post_json(_OSV_QUERYBATCH_URL, {"queries": queries})
    results = response.get("results", [])
    ids_per_pin: list[list[str]] = []
    for result in results if isinstance(results, list) else []:
        vulns = result.get("vulns", []) if isinstance(result, dict) else []
        ids_per_pin.append(
            [v["id"] for v in vulns if isinstance(v, dict) and isinstance(v.get("id"), str)]
        )
    return ids_per_pin


def _fetch_summary(vuln_id: str) -> str:
    fallback = f"Known vulnerability {vuln_id}"
    try:
        detail = _get_json(_OSV_VULN_URL.format(id=vuln_id))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return fallback
    summary = detail.get("summary")
    return str(summary) if isinstance(summary, str) and summary else fallback


class OsvScanner:
    """Queries OSV.dev for known vulnerabilities in exactly-pinned dependencies."""

    name = "osv"

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        if languages and "python" not in languages:
            return
        pins = _find_pins(root)
        if not pins:
            return
        pin_list = list(pins.keys())
        try:
            ids_per_pin = _query_vulnerable_ids(pin_list)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return
        summary_cache: dict[str, str] = {}
        for (dep_name, dep_version), vuln_ids in zip(pin_list, ids_per_pin, strict=True):
            manifest = pins[(dep_name, dep_version)]
            for vuln_id in vuln_ids:
                if vuln_id not in summary_cache:
                    summary_cache[vuln_id] = _fetch_summary(vuln_id)
                yield RawFinding(
                    rule_id=vuln_id,
                    message=f"{summary_cache[vuln_id]} ({dep_name}=={dep_version})",
                    location=SourceLocation(path=manifest, start_line=1),
                    severity_hint=None,
                    cwe=None,
                    raw={"package": dep_name, "version": dep_version, "ecosystem": _ECOSYSTEM},
                )
