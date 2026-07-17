"""Filesystem-walking conventions shared by every adapter that scans or
parses source trees.

Not project-specific business logic, but a real, pure, no-I/O constant that
would otherwise drift across `cortexward-scanners`' two adapters and
`cortexward-cpg`'s Python `LanguageProvider` — import-linter's own
sibling-adapter contracts forbid either package from importing the other
("Scanner adapters do not depend on other adapters or interfaces", "CPG
engine does not depend on other adapters or interfaces"), so
`cortexward.domain` is the only shared home this can live in without
changing the dependency direction. A plain tuple, not a `frozenset`,
deliberately: iteration order must stay deterministic (Python's string
hashing is randomized per process), matching this project's own
offline-determinism bar for tool invocations.
"""

from __future__ import annotations

EXCLUDED_DIR_NAMES: tuple[str, ...] = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".hypothesis",
)

__all__ = ["EXCLUDED_DIR_NAMES"]
