"""Tests for the entry-point-driven plugin registry.

Uses real ``importlib.metadata.EntryPoint`` objects pointing at fixture
classes, with only ``metadata.entry_points`` itself monkeypatched — so
``PluginRegistry.load`` performs a genuine dynamic import, proving discovery
actually works end to end rather than being faked.

The fixtures live in a small synthetic module registered directly into
``sys.modules`` rather than this test file itself: under
``--import-mode=importlib`` (used so sibling packages' ``tests/`` trees
don't collide, see pyproject.toml) pytest derives each test module's dotted
name from its file path, which here would include the hyphenated directory
``cortexward-core`` — not a valid Python identifier, and not usable as an
entry point's ``module:attr`` target. Registering our own cleanly-named
module sidesteps that entirely.
"""

from __future__ import annotations

import sys
import types
from importlib import metadata

import pytest

import cortexward.plugins.registry as registry_module
from cortexward.plugins import PluginGroup, PluginNotFoundError, PluginRegistry, registry_for

pytestmark = pytest.mark.unit

_FIXTURE_MODULE_NAME = "cortexward_plugin_registry_test_fixtures"


class _FixtureScanner:
    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose


class _NotCallable:
    """A plugin author mistake: an entry point resolving to an instance."""


_NOT_CALLABLE_INSTANCE = _NotCallable()


def _install_fixture_module() -> None:
    """Register a real, importable module holding the fixture objects."""
    module = types.ModuleType(_FIXTURE_MODULE_NAME)
    module.__dict__["_FixtureScanner"] = _FixtureScanner
    module.__dict__["_NOT_CALLABLE_INSTANCE"] = _NOT_CALLABLE_INSTANCE
    sys.modules[_FIXTURE_MODULE_NAME] = module


_install_fixture_module()


def _fake_entry_points(*, group: str) -> tuple[metadata.EntryPoint, ...]:
    catalog: dict[str, tuple[metadata.EntryPoint, ...]] = {
        "cortexward.scanners": (
            metadata.EntryPoint(
                name="fixture",
                value=f"{_FIXTURE_MODULE_NAME}:_FixtureScanner",
                group="cortexward.scanners",
            ),
        ),
        "cortexward.llm": (
            metadata.EntryPoint(
                name="broken",
                value=f"{_FIXTURE_MODULE_NAME}:_NOT_CALLABLE_INSTANCE",
                group="cortexward.llm",
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
    registry = PluginRegistry("cortexward.sandbox")
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
    assert registry.group == "cortexward.vcs"
