"""Tests for the entry-point-driven plugin registry.

Uses real ``importlib.metadata.EntryPoint`` objects pointing at fixture
classes defined in this module, with only ``metadata.entry_points`` itself
monkeypatched — so ``PluginRegistry.load`` performs a genuine dynamic import,
proving discovery actually works end to end rather than being faked.
"""

from __future__ import annotations

from importlib import metadata

import pytest

import aegisforge.plugins.registry as registry_module
from aegisforge.plugins import PluginGroup, PluginNotFoundError, PluginRegistry, registry_for

pytestmark = pytest.mark.unit


class _FixtureScanner:
    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose


class _NotCallable:
    """A plugin author mistake: an entry point resolving to an instance."""


_NOT_CALLABLE_INSTANCE = _NotCallable()


def _fake_entry_points(*, group: str) -> tuple[metadata.EntryPoint, ...]:
    catalog: dict[str, tuple[metadata.EntryPoint, ...]] = {
        "aegisforge.scanners": (
            metadata.EntryPoint(
                name="fixture",
                value="tests.unit.plugins.test_registry:_FixtureScanner",
                group="aegisforge.scanners",
            ),
        ),
        "aegisforge.llm": (
            metadata.EntryPoint(
                name="broken",
                value="tests.unit.plugins.test_registry:_NOT_CALLABLE_INSTANCE",
                group="aegisforge.llm",
            ),
        ),
    }
    return catalog.get(group, ())


@pytest.fixture(autouse=True)
def _patch_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module.metadata, "entry_points", _fake_entry_points)


def test_available_lists_installed_plugins_without_importing() -> None:
    registry = registry_for(PluginGroup.SCANNERS)
    assert set(registry.available()) == {"fixture"}


def test_available_empty_group_returns_empty_mapping() -> None:
    registry = PluginRegistry("aegisforge.sandbox")
    assert registry.available() == {}


def test_load_imports_and_returns_the_factory() -> None:
    registry = registry_for(PluginGroup.SCANNERS)
    factory = registry.load("fixture")
    assert factory is _FixtureScanner


def test_create_instantiates_the_plugin() -> None:
    registry = registry_for(PluginGroup.SCANNERS)
    instance = registry.create("fixture", verbose=True)
    assert isinstance(instance, _FixtureScanner)
    assert instance.verbose is True


def test_load_missing_plugin_raises_with_available_names() -> None:
    registry = registry_for(PluginGroup.SCANNERS)
    with pytest.raises(PluginNotFoundError) as excinfo:
        registry.load("does-not-exist")
    assert excinfo.value.available == ("fixture",)
    assert "does-not-exist" in str(excinfo.value)


def test_load_non_callable_target_raises_type_error() -> None:
    registry = registry_for(PluginGroup.LLM)
    with pytest.raises(TypeError, match="non-callable"):
        registry.load("broken")


def test_group_property_and_string_coercion() -> None:
    registry = PluginRegistry(PluginGroup.VCS)
    assert registry.group == "aegisforge.vcs"
