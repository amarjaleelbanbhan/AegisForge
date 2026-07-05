"""Shared fixtures for the aegisforge-cpg test suite.

See ``packages/aegisforge-core/tests/conftest.py`` for why builders are
exposed as fixtures rather than plain importable helpers: with no
``__init__.py`` under ``tests/`` (required so each workspace package's
``tests/`` tree doesn't collide with its siblings), fixture injection is the
portable way to share builders across test modules.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from aegisforge.domain import SourceLocation

MakeLocation = Callable[..., SourceLocation]


@pytest.fixture
def make_location() -> MakeLocation:
    """Factory fixture building a throwaway :class:`SourceLocation`."""

    def _make_location(line: int = 1, path: str = "app.py") -> SourceLocation:
        return SourceLocation(path=path, start_line=line)

    return _make_location
