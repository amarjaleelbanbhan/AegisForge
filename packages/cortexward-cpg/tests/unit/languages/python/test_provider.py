"""Tests for the Python LanguageProvider (detection, manifests, parsing)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cortexward.cpg import InMemoryCodeGraph, NodeKind
from cortexward.languages.python import PythonLanguageProvider
from cortexward.ports import LanguageProvider

pytestmark = pytest.mark.unit


@pytest.fixture
def provider() -> PythonLanguageProvider:
    return PythonLanguageProvider()


def _symlinks_supported() -> bool:
    """Whether this process can create symlinks (needs Developer Mode or
    admin on Windows; unprivileged elsewhere)."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "target"
        target.write_text("x", encoding="utf-8")
        try:
            os.symlink(target, Path(td) / "link")
        except OSError:
            return False
    return True


_HAS_SYMLINKS = _symlinks_supported()


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
        self, tmp_path: Path, provider: PythonLanguageProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A real repo can contain a file that's unreadable by the time it's
        # actually opened (permission changes, a deleted-then-recreated
        # file, a TOCTOU race with a concurrent process) even though it was
        # a genuine file, not a directory or symlink, when listed; parsing
        # must skip it rather than crash the whole run.
        (tmp_path / "trap.py").write_text("x = 1\n")
        (tmp_path / "app.py").write_text("y = 1\n")
        trap_path = (tmp_path / "trap.py").resolve()

        real_read_bytes = Path.read_bytes

        def _flaky_read_bytes(self: Path) -> bytes:
            if self.resolve() == trap_path:
                raise OSError("simulated unreadable file")
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _flaky_read_bytes)
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

    @pytest.mark.skipif(not _HAS_SYMLINKS, reason="symlinks not supported in this environment")
    def test_a_symlinked_file_inside_root_is_not_parsed(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        # A malicious/crafted repository is untrusted input (ADR-0004): a
        # symlink inside the parsed root pointing at a real file elsewhere
        # on disk must not be followed into the graph.
        (tmp_path / "app.py").write_text("x = 1\n")
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.py"
            outside.write_text("SHOULD_NOT_APPEAR = 1\n")
            (tmp_path / "link.py").symlink_to(outside)
            graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        paths = {node_id.split("#", 1)[0] for node_id in graph.nodes}
        assert paths == {"app.py"}

    @pytest.mark.skipif(not _HAS_SYMLINKS, reason="symlinks not supported in this environment")
    def test_a_symlinked_directory_inside_root_is_not_traversed(
        self, tmp_path: Path, provider: PythonLanguageProvider
    ) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")
        with tempfile.TemporaryDirectory() as outside_dir:
            (Path(outside_dir) / "outside.py").write_text("SHOULD_NOT_APPEAR = 1\n")
            (tmp_path / "linked_dir").symlink_to(outside_dir, target_is_directory=True)
            graph = provider.parse(tmp_path)
        assert isinstance(graph, InMemoryCodeGraph)
        paths = {node_id.split("#", 1)[0] for node_id in graph.nodes}
        assert paths == {"app.py"}
