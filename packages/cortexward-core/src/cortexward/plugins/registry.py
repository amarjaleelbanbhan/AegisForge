"""Plugin discovery and loading via Python entry points (MPS §17).

Adding a scanner, language, LLM backend, sandbox, VCS host, storage backend,
or reporter to CortexWard means shipping a package that registers under the
matching :class:`~cortexward.plugins.groups.PluginGroup`. This module never
imports an adapter package directly; discovery is driven entirely by
installed package metadata, so the core requires zero changes to gain a new
plugin.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import metadata as metadata  # noqa: PLC0414 - intentional re-export for tests
from typing import cast

from cortexward.plugins.groups import PluginGroup


class PluginNotFoundError(LookupError):
    """Raised when a requested plugin name is not registered for a group."""

    def __init__(self, group: str, name: str, available: Mapping[str, object]) -> None:
        self.group = group
        self.name = name
        self.available = tuple(sorted(available))
        super().__init__(
            f"no plugin named {name!r} registered for group {group!r}; "
            f"available: {self.available or '(none installed)'}"
        )


class PluginRegistry:
    """Discovers and loads plugins registered under one entry-point group."""

    def __init__(self, group: PluginGroup | str) -> None:
        self._group = str(group)

    @property
    def group(self) -> str:
        return self._group

    def available(self) -> Mapping[str, metadata.EntryPoint]:
        """Installed plugin names for this group, without importing any of them."""
        entry_points = metadata.entry_points(group=self._group)
        return {ep.name: ep for ep in entry_points}

    def load(self, name: str) -> Callable[..., object]:
        """Import and return the factory (class or callable) registered as `name`.

        Raises :class:`PluginNotFoundError` if no plugin is registered under
        that name for this group.
        """
        available = self.available()
        if name not in available:
            raise PluginNotFoundError(self._group, name, available)
        loaded = available[name].load()
        if not callable(loaded):
            raise TypeError(
                f"plugin {name!r} in group {self._group!r} resolved to a "
                f"non-callable object ({loaded!r}); entry points must point "
                f"to a class or factory function"
            )
        return cast("Callable[..., object]", loaded)

    def create(self, name: str, /, *args: object, **kwargs: object) -> object:
        """Load the plugin named `name` and instantiate it with the given args."""
        factory = self.load(name)
        return factory(*args, **kwargs)


def registry_for(group: PluginGroup | str) -> PluginRegistry:
    """Convenience constructor: ``registry_for(PluginGroup.SCANNERS)``."""
    return PluginRegistry(group)
