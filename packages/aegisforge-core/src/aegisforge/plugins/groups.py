"""The canonical entry-point groups AegisForge plugins register under.

A plugin package declares itself in its own ``pyproject.toml``, e.g.::

    [project.entry-points."aegisforge.scanners"]
    semgrep = "aegisforge_scanners.semgrep:SemgrepScanner"

The group string is the contract between a plugin and the core; it never
changes even as the plugin's own module path does. See MPS §17.
"""

from __future__ import annotations

from enum import StrEnum


class PluginGroup(StrEnum):
    """One entry-point group per port in the catalog (MPS §17.1)."""

    LANGUAGES = "aegisforge.languages"
    """Registers a :class:`aegisforge.ports.LanguageProvider`."""

    SCANNERS = "aegisforge.scanners"
    """Registers a :class:`aegisforge.ports.ScannerPort`."""

    LLM = "aegisforge.llm"
    """Registers a :class:`aegisforge.ports.LLMPort` (or ``EmbeddingPort``)."""

    SANDBOX = "aegisforge.sandbox"
    """Registers a :class:`aegisforge.ports.SandboxPort`."""

    VCS = "aegisforge.vcs"
    """Registers a :class:`aegisforge.ports.VCSPort`."""

    STORAGE = "aegisforge.storage"
    """Registers a :class:`aegisforge.ports.StoragePort`."""

    REPORTERS = "aegisforge.reporters"
    """Registers a :class:`aegisforge.ports.ReporterPort`."""
