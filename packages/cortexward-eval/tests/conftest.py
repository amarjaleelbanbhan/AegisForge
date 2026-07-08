"""Shared fixtures for the cortexward-eval test suite.

See ``packages/cortexward-core/tests/conftest.py`` for why builders are
exposed as fixtures rather than plain importable helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from cortexward.domain import Finding, Provenance, Severity, SourceLocation

MakeFinding = Callable[..., Finding]

_PROV = Provenance(producer="test", producer_version="0")


@pytest.fixture
def make_finding() -> MakeFinding:
    """Factory fixture building a :class:`Finding` with a controllable location and CWE."""

    def _make_finding(
        *,
        finding_id: str | None = None,
        path: str = "app.py",
        start_line: int = 10,
        end_line: int | None = None,
        cwe: int | None = 89,
        severity: Severity = Severity.HIGH,
    ) -> Finding:
        return Finding(
            id=finding_id if finding_id is not None else f"find_{uuid4().hex[:16]}",
            rule_id="test.rule",
            title="Test finding",
            message="A potential issue was detected.",
            severity=severity,
            cwe=cwe,
            locations=(SourceLocation(path=path, start_line=start_line, end_line=end_line),),
            provenance=_PROV,
        )

    return _make_finding
