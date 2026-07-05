"""Conformance test for the Scanner port."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from aegisforge.domain import SourceLocation
from aegisforge.ports import RawFinding, ScannerPort

pytestmark = pytest.mark.unit


class _FakeScanner:
    name = "fake-semgrep"

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        yield RawFinding(
            rule_id="py.sql-injection",
            message="possible SQL injection",
            location=SourceLocation(path="app/db.py", start_line=10),
            cwe=89,
        )


def test_fake_scanner_satisfies_protocol() -> None:
    assert isinstance(_FakeScanner(), ScannerPort)


def test_scan_yields_raw_findings(tmp_path: Path) -> None:
    findings = list(_FakeScanner().scan(tmp_path))
    assert len(findings) == 1
    assert findings[0].rule_id == "py.sql-injection"
    assert findings[0].raw == {}
