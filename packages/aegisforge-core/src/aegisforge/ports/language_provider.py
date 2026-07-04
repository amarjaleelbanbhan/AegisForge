"""LanguageProvider port: per-language parsing and metadata (MPS §6.1, §12).

Adding a language to AegisForge means shipping a package that registers a
:class:`LanguageProvider` under the ``aegisforge.languages`` entry-point group
(see :mod:`aegisforge.plugins.registry`) — the core never changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from aegisforge.ports.code_graph import CodeGraph


@runtime_checkable
class LanguageProvider(Protocol):
    """Adapts a single programming language to the AegisForge core.

    Implementations MUST NOT execute any code belonging to the analyzed
    project — no build scripts, no package post-install hooks, no
    interpreter invocation of project code (ADR-0004). Parsing source files
    and reading dependency manifests is permitted; running them is not.
    """

    @property
    def language(self) -> str:
        """Stable identifier for this language, e.g. ``"python"``."""
        ...

    def detect(self, root: Path) -> bool:
        """Return ``True`` if this provider can analyze the tree at ``root``."""
        ...

    def parse(self, root: Path) -> CodeGraph:
        """Build a :class:`~aegisforge.ports.code_graph.CodeGraph` for ``root``."""
        ...

    def dependency_manifests(self, root: Path) -> Sequence[Path]:
        """Dependency manifest files this provider recognizes under ``root``.

        E.g. ``requirements.txt`` / ``pyproject.toml`` for Python. Manifests
        are read for the dependency graph; they are never executed.
        """
        ...
