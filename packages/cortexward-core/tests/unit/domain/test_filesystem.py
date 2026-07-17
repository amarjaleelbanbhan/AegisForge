"""Unit tests for `cortexward.domain.filesystem.EXCLUDED_DIR_NAMES`."""

from __future__ import annotations

import pytest

from cortexward.domain import EXCLUDED_DIR_NAMES

pytestmark = pytest.mark.unit


class TestExcludedDirNames:
    def test_is_a_tuple_not_a_set(self) -> None:
        # Deterministic iteration order matters here (see the module
        # docstring): a plain set/frozenset of strings has process-random
        # iteration order under Python's default hash randomization.
        assert isinstance(EXCLUDED_DIR_NAMES, tuple)

    def test_contains_common_vcs_and_tooling_directories(self) -> None:
        assert ".git" in EXCLUDED_DIR_NAMES
        assert ".venv" in EXCLUDED_DIR_NAMES
        assert "__pycache__" in EXCLUDED_DIR_NAMES
        assert "node_modules" in EXCLUDED_DIR_NAMES

    def test_has_no_duplicates(self) -> None:
        assert len(EXCLUDED_DIR_NAMES) == len(set(EXCLUDED_DIR_NAMES))
