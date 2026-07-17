"""The Python reference :class:`~cortexward.ports.LanguageProvider` (MPS §6.1).

Parses Python source with tree-sitter into the CPG's AST layer
(:mod:`cortexward.languages.python._ast_walker`). Never executes project
code: no ``setup.py``, no imports of the analyzed package, no subprocess
calls — only parsing and manifest reading (ADR-0004).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from cortexward.cpg import GraphBuilder
from cortexward.domain import EXCLUDED_DIR_NAMES
from cortexward.languages.python._ast_walker import walk_module
from cortexward.languages.python._call_graph_builder import build_call_graph
from cortexward.languages.python._cfg_builder import build_control_flow
from cortexward.languages.python._dfg_builder import build_data_flow
from cortexward.ports import CodeGraph

_DEPENDENCY_MANIFEST_NAMES = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
)


def _is_excluded_dir_name(name: str) -> bool:
    return name in EXCLUDED_DIR_NAMES or name.endswith(".egg-info")


def _iter_python_files(root: Path) -> Sequence[Path]:
    """Every `.py` file under `root`, never crossing a symlink.

    `os.walk(..., followlinks=False)` — not `Path.rglob()` — is what makes
    this reliable: `rglob` only gained a `recurse_symlinks=False` default in
    Python 3.13, so on the 3.11/3.12 this project's own CI matrix still
    supports, `rglob` would silently follow a symlinked directory inside a
    parsed (untrusted, per ADR-0004) repository out past `root`.
    """
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not _is_excluded_dir_name(name)]
        current = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = current / filename
            if path.is_symlink():
                continue
            files.append(path)
    return sorted(files)


class PythonLanguageProvider:
    """Parses Python source trees into a :class:`CodeGraph`."""

    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(Language(tspython.language()))

    def detect(self, root: Path) -> bool:
        if any((root / name).exists() for name in _DEPENDENCY_MANIFEST_NAMES):
            return True
        return any(_iter_python_files(root))

    def parse(self, root: Path) -> CodeGraph:
        builder = GraphBuilder(language=self.language)
        for file_path in _iter_python_files(root):
            try:
                source = file_path.read_bytes()
            except OSError:
                continue
            tree = self._parser.parse(source)
            relative = str(file_path.relative_to(root))
            result = walk_module(tree.root_node, source=source, file_path=relative, builder=builder)
            cfg_edges = build_control_flow(
                tree.root_node, node_ids=result.node_ids, builder=builder
            )
            build_data_flow(
                tree.root_node,
                node_ids=result.node_ids,
                cfg_edges=cfg_edges,
                source=source,
                builder=builder,
            )
            build_call_graph(
                tree.root_node, node_ids=result.node_ids, source=source, builder=builder
            )
        return builder.build()

    def dependency_manifests(self, root: Path) -> Sequence[Path]:
        return tuple(root / name for name in _DEPENDENCY_MANIFEST_NAMES if (root / name).is_file())
