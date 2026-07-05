"""Tests for cortexward.core package metadata."""

from __future__ import annotations

import re

import pytest

from cortexward.core import version

pytestmark = pytest.mark.unit


def test_version_reads_installed_distribution_metadata() -> None:
    reported = version()
    assert re.match(r"^\d+\.\d+\.\d+", reported), reported
