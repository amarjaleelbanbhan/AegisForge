"""CortexWard core metadata.

``cortexward`` itself is a namespace package (PEP 420): it has no ``__init__.py``
at its root, so that independently-versioned distributions (``cortexward-cpg``,
``cortexward-llm``, ``cortexward-orchestrator``, ...) can each contribute their
own subpackage under the shared ``cortexward.*`` namespace without conflict.

``cortexward-core`` is the one distribution every installation requires, so it
is the natural, stable home for package-level metadata such as the version.
Prefer :func:`version`, which reads installed distribution metadata and stays
correct for editable installs and re-packaging alike, over a hardcoded
constant.
"""

from __future__ import annotations

from importlib import metadata

_DISTRIBUTION_NAME = "cortexward-core"


def version() -> str:
    """Return the installed version of the ``cortexward-core`` distribution.

    Raises :class:`importlib.metadata.PackageNotFoundError` if the package is
    not installed (e.g. running from a source checkout without an editable
    install) rather than silently returning a placeholder.
    """
    return metadata.version(_DISTRIBUTION_NAME)


__all__ = ["version"]
