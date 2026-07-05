"""The canonical entry-point groups CortexWard plugins register under.

A plugin package declares itself in its own ``pyproject.toml``, e.g.::

    [project.entry-points."cortexward.scanners"]
    semgrep = "cortexward_scanners.semgrep:SemgrepScanner"

The group string is the contract between a plugin and the core; it never
changes even as the plugin's own module path does. See MPS §17.
"""

from __future__ import annotations

from enum import StrEnum


class PluginGroup(StrEnum):
    """One entry-point group per port in the catalog (MPS §17.1)."""

    LANGUAGES = "cortexward.languages"
    """Registers a :class:`cortexward.ports.LanguageProvider`."""

    SCANNERS = "cortexward.scanners"
    """Registers a :class:`cortexward.ports.ScannerPort`."""

    LLM = "cortexward.llm"
    """Registers a :class:`cortexward.ports.LLMPort` (or ``EmbeddingPort``)."""

    SANDBOX = "cortexward.sandbox"
    """Registers a :class:`cortexward.ports.SandboxPort`."""

    VCS = "cortexward.vcs"
    """Registers a :class:`cortexward.ports.VCSPort`."""

    STORAGE = "cortexward.storage"
    """Registers a :class:`cortexward.ports.StoragePort`."""

    REPORTERS = "cortexward.reporters"
    """Registers a :class:`cortexward.ports.ReporterPort`."""
