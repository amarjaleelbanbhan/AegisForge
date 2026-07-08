"""Parses Python dependency manifests into structured, never-executed records.

Reads (never executes) the manifest kinds `PythonLanguageProvider.
dependency_manifests` already discovers — `pyproject.toml` (PEP 621),
`requirements*.txt`, `setup.cfg`, and `Pipfile` — extracting each declared
dependency's name, version constraint, and whether it's a runtime, dev, or
optional dependency.

**Explicitly out of scope:** `setup.py`. Its dependency list
(`install_requires`) is only reliably obtainable by executing it, which
violates the non-execution guarantee (ADR-0004, MPS §12) — a `setup.py` is
still returned by `dependency_manifests`, but this parser does not attempt
to extract dependencies from it (`parse_dependencies` returns an empty
sequence for it, not an error). Poetry's own dependency tables
(`[tool.poetry.dependencies]`, a version-string-keyed-by-name shape distinct
from PEP 621's list-of-specifier-strings) are likewise out of scope for now.
PEP 508 environment markers, extras, and VCS/URL requirements are not
parsed in depth — the raw remainder after the package name is kept as the
version constraint verbatim rather than guessed at.

**Not yet wired into the CodeGraph.** The CPG spec (MPS §12) names a
"dependency graph" layer, but the shape that would take as graph nodes/edges
(one node per package? per manifest? how it composes with CALLS/DFG) isn't
pinned down. This module intentionally returns plain data, not graph nodes —
exactly what a future dependency-scanning adapter (Phase 3) needs (name +
version constraint + manifest source + kind), without forcing an early,
unreviewed graph-shape decision.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DependencyKind(StrEnum):
    """Which part of a manifest a dependency was declared in."""

    RUNTIME = "runtime"
    DEV = "dev"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class Dependency:
    """One dependency declaration read from a manifest file."""

    name: str
    version_constraint: str | None
    manifest: str
    """The manifest file's name, e.g. `"pyproject.toml"` (not a full path)."""
    kind: DependencyKind


_REQUIREMENT_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def _parse_requirement_line(line: str) -> tuple[str, str | None] | None:
    """`"requests>=2.0  # comment"` -> `("requests", ">=2.0")`; `None` if unparseable."""
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith("-"):
        return None
    match = _REQUIREMENT_LINE.match(stripped)
    if match is None:
        return None
    name, _extras, rest = match.groups()
    return name, (rest.strip() or None)


def _parse_pep621_list(
    entries: list[object], *, manifest: str, kind: DependencyKind
) -> list[Dependency]:
    deps: list[Dependency] = []
    for entry in entries:
        if not isinstance(entry, str):
            continue
        parsed = _parse_requirement_line(entry)
        if parsed is None:
            continue
        name, constraint = parsed
        deps.append(
            Dependency(name=name, version_constraint=constraint, manifest=manifest, kind=kind)
        )
    return deps


def _parse_pyproject_toml(path: Path) -> list[Dependency]:
    data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    deps: list[Dependency] = []
    runtime = project.get("dependencies")
    if isinstance(runtime, list):
        deps.extend(_parse_pep621_list(runtime, manifest=path.name, kind=DependencyKind.RUNTIME))
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group_entries in optional.values():
            if isinstance(group_entries, list):
                deps.extend(
                    _parse_pep621_list(
                        group_entries, manifest=path.name, kind=DependencyKind.OPTIONAL
                    )
                )
    return deps


def _parse_setup_cfg(path: Path) -> list[Dependency]:
    parser = ConfigParser()
    parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    deps: list[Dependency] = []
    if parser.has_option("options", "install_requires"):
        for line in parser.get("options", "install_requires").splitlines():
            parsed = _parse_requirement_line(line)
            if parsed is None:
                continue
            name, constraint = parsed
            deps.append(
                Dependency(
                    name=name,
                    version_constraint=constraint,
                    manifest=path.name,
                    kind=DependencyKind.RUNTIME,
                )
            )
    if parser.has_section("options.extras_require"):
        for _extra_name, raw in parser.items("options.extras_require"):
            for line in raw.splitlines():
                parsed = _parse_requirement_line(line)
                if parsed is None:
                    continue
                name, constraint = parsed
                deps.append(
                    Dependency(
                        name=name,
                        version_constraint=constraint,
                        manifest=path.name,
                        kind=DependencyKind.OPTIONAL,
                    )
                )
    return deps


def _parse_pipfile(path: Path) -> list[Dependency]:
    data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    deps: list[Dependency] = []
    for section, kind in (
        ("packages", DependencyKind.RUNTIME),
        ("dev-packages", DependencyKind.DEV),
    ):
        table = data.get(section)
        if not isinstance(table, dict):
            continue
        for name, value in table.items():
            constraint = value if isinstance(value, str) and value != "*" else None
            deps.append(
                Dependency(name=name, version_constraint=constraint, manifest=path.name, kind=kind)
            )
    return deps


def _parse_requirements_txt(path: Path) -> list[Dependency]:
    kind = DependencyKind.DEV if "dev" in path.stem.lower() else DependencyKind.RUNTIME
    deps: list[Dependency] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = _parse_requirement_line(raw_line)
        if parsed is None:
            continue
        name, constraint = parsed
        deps.append(
            Dependency(name=name, version_constraint=constraint, manifest=path.name, kind=kind)
        )
    return deps


_PARSERS_BY_EXACT_NAME = {
    "pyproject.toml": _parse_pyproject_toml,
    "setup.cfg": _parse_setup_cfg,
    "Pipfile": _parse_pipfile,
}


def parse_dependencies(manifest_path: Path) -> Sequence[Dependency]:
    """Every dependency declared in `manifest_path`, or `()` if unreadable/unrecognized.

    Malformed manifest content (invalid TOML/INI, an unreadable file) yields
    an empty sequence rather than raising — parsed input is untrusted
    (ADR-0004), and one broken manifest must not abort analysis of the rest
    of a project.
    """
    parse = _PARSERS_BY_EXACT_NAME.get(manifest_path.name)
    if (
        parse is None
        and manifest_path.name.startswith("requirements")
        and manifest_path.suffix == ".txt"
    ):
        parse = _parse_requirements_txt
    if parse is None:
        return ()
    try:
        return tuple(parse(manifest_path))
    except (OSError, ValueError, ConfigParserError):
        return ()
