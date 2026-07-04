"""Tests for aegisforge.core package metadata."""

from __future__ import annotations

import re

import pytest

from aegisforge.core import version

pytestmark = pytest.mark.unit


def test_version_reads_installed_distribution_metadata() -> None:
    reported = version()
    assert re.match(r"^\d+\.\d+\.\d+", reported), reported
