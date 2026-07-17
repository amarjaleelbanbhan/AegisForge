"""The CortexWard plugin system: entry-point groups and the registry.

This package depends only on :mod:`cortexward.domain` (transitively, via
ports it may reference in tests/usage) and the standard library; it never
imports a concrete adapter package, enforced by the "Plugin registry does not
depend on concrete adapters" import-linter contract.
"""

from __future__ import annotations

from cortexward.plugins.groups import PluginGroup
from cortexward.plugins.registry import PluginNotFoundError, PluginRegistry, registry_for

__all__ = [
    "PluginGroup",
    "PluginNotFoundError",
    "PluginRegistry",
    "registry_for",
]
