"""Tests for the Python LanguageProvider (detection, manifests, parsing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.cpg import InMemoryCodeGraph, NodeKind
from cortexward.languages.python import PythonLanguageProvider
from cortexward.ports import LanguageProvider

pytestmark = pytest.mark.unit


@pytest.fixture
def provider() -> PythonLanguageProvider:
    return PythonLanguageProvider()


def test_satisfies_language_provider_protocol(provider: PythonLanguageProvider) -> None:
    assert isinstance(provider, LanguageProvider)
    assert provider.language == "python"


class TestDetect:
    def test_detects_via_pyproject_toml(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        assert provider.detect(tmp_path) is True

    def test_detects_via_loose_py_files(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "script.py").write_text("print('hi')\n")
        assert provider.detect(tmp_path) is True

    def test_does_not_detect_unrelated_tree(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "README.md").write_text("# not python\n")
        assert provider.detect(tmp_path) is False


class TestDependencyManifests:
    def test_returns_only_existing_manifests(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "requirements.txt").write_text("pydantic\n")
        manifests = provider.dependency_manifests(tmp_path)
        assert set(manifests) == {tmp_path / "pyproject.toml", tmp_path / "requirements.txt"}

    def test_empty_tree_has_no_manifests(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        assert provider.dependency_manifests(tmp_path) == ()


class TestParse:
    def test_parses_single_file_into_a_graph(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "app.py").write_text("def main():\n    pass\n")
        graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        assert graph.language == "python"
        function_nodes = [n for n in graph.nodes.values() if n.kind is NodeKind.FUNCTION]
        assert len(function_nodes) == 1
        assert len(graph.entrypoints()) == 1  # def main()

    def test_parses_multiple_files_into_one_graph(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "a.py").write_text("def f():\n    pass\n")
        (tmp_path / "b.py").write_text("def g():\n    pass\n")
        graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        function_names = {
            n.properties.get("name") for n in graph.nodes.values() if n.kind is NodeKind.FUNCTION
        }
        assert function_names == {"f", "g"}

    def test_node_ids_are_scoped_by_relative_path(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
        graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        assert any(node_id.startswith("pkg") for node_id in graph.nodes)

    def test_excludes_noise_directories(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")
        venv_dir = tmp_path / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "installed.py").write_text("SHOULD_NOT_APPEAR = 1\n")
        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "cached.py").write_text("SHOULD_NOT_APPEAR_EITHER = 1\n")

        graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        paths = {node_id.split("#", 1)[0] for node_id in graph.nodes}
        assert "app.py" in paths
        assert not any(".venv" in p or "__pycache__" in p for p in paths)

    def test_unreadable_path_is_skipped_not_fatal(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        # A directory literally named "*.py" matches the glob but raises
        # IsADirectoryError (an OSError) on read; parsing must skip it rather
        # than crash the whole run, since a real repo can contain oddities
        # like broken symlinks that fail to read for similar reasons.
        (tmp_path / "trap.py").mkdir()
        (tmp_path / "app.py").write_text("x = 1\n")

        graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        paths = {node_id.split("#", 1)[0] for node_id in graph.nodes}
        assert paths == {"app.py"}

    def test_empty_tree_yields_empty_graph(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        assert dict(graph.nodes) == {}
        assert graph.entrypoints() == ()
