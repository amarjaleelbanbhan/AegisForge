"""The Python reference language provider (MPS §6.1)."""

from __future__ import annotations

from cortexward.languages.python._manifest_parser import (
    Dependency,
    DependencyKind,
    parse_dependencies,
)
from cortexward.languages.python.provider import PythonLanguageProvider

__all__ = ["Dependency", "DependencyKind", "PythonLanguageProvider", "parse_dependencies"]
