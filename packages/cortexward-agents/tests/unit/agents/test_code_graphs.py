"""Unit tests for `build_code_graphs`.

Most tests use the real registered `PythonLanguageProvider` (installed
alongside this package in the workspace venv) against real source files
written to `tmp_path`, per this codebase's established preference for
exercising real components wherever the target is genuinely reachable.
Resilience to a broken/raising provider is tested against a monkeypatched
registry, since no real provider fails on demand.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

import cortexward.agents.code_graphs as code_graphs_module
from cortexward.agents import build_code_graphs
from cortexward.ports import CodeGraph

pytestmark = pytest.mark.unit


class TestRealPythonProviderDiscovery:
    def test_empty_directory_yields_no_graphs(self, tmp_path: Path) -> None:
        assert build_code_graphs(tmp_path) == {}

    def test_directory_with_python_files_is_auto_detected(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
        graphs = build_code_graphs(tmp_path)
        assert "python" in graphs
        assert isinstance(graphs["python"], CodeGraph)

    def test_explicit_language_bypasses_detect(self, tmp_path: Path) -> None:
        # No .py files and no manifest -- detect() would say no -- but an
        # explicit languages=("python",) still asks the provider to parse.
        graphs = build_code_graphs(tmp_path, languages=("python",))
        assert "python" in graphs

    def test_unlisted_language_is_skipped_even_with_matching_files(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
        assert build_code_graphs(tmp_path, languages=("javascript",)) == {}

    def test_a_dependency_manifest_alone_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
        graphs = build_code_graphs(tmp_path)
        assert "python" in graphs


class TestResilience:
    def test_a_provider_that_raises_while_parsing_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BrokenProvider:
            language = "broken"

            def detect(self, root: Path) -> bool:
                return True

            def parse(self, root: Path) -> CodeGraph:
                raise RuntimeError("parser exploded")

        class _FakeRegistry:
            def available(self) -> Mapping[str, object]:
                return {"broken": object()}

            def create(self, name: str, /, *args: object, **kwargs: object) -> object:
                return _BrokenProvider()

        monkeypatch.setattr(code_graphs_module, "registry_for", lambda _group: _FakeRegistry())
        assert build_code_graphs(tmp_path) == {}

    def test_one_broken_provider_does_not_affect_a_working_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BrokenProvider:
            language = "broken"

            def detect(self, root: Path) -> bool:
                return True

            def parse(self, root: Path) -> CodeGraph:
                raise RuntimeError("parser exploded")

        class _WorkingProvider:
            language = "ok"

            def detect(self, root: Path) -> bool:
                return True

            def parse(self, root: Path) -> CodeGraph:
                return cast("CodeGraph", _StubGraph())

        class _StubGraph:
            language = "ok"

            def entrypoints(self) -> tuple[str, ...]:
                return ()

            def reachable(self, sources: object, sink: object) -> bool:
                return False

            def taint(self, *args: object, **kwargs: object) -> tuple[object, ...]:
                return ()

            def callers(self, function: object) -> tuple[str, ...]:
                return ()

            def slice(self, node: object) -> tuple[str, ...]:
                return ()

            def location_of(self, node: object) -> object:
                raise KeyError(node)

            def nodes_at(self, path: str, line: int) -> tuple[str, ...]:
                return ()

        class _FakeRegistry:
            def available(self) -> Mapping[str, object]:
                return {"broken": object(), "ok": object()}

            def create(self, name: str, /, *args: object, **kwargs: object) -> object:
                return _BrokenProvider() if name == "broken" else _WorkingProvider()

        monkeypatch.setattr(code_graphs_module, "registry_for", lambda _group: _FakeRegistry())
        graphs = build_code_graphs(tmp_path)
        assert set(graphs) == {"ok"}
