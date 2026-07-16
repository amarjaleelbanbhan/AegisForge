"""Unit tests for `fingerprint_for`."""

from __future__ import annotations

import pytest

from cortexward.domain import Finding, Provenance, SourceLocation, fingerprint_for

pytestmark = pytest.mark.unit


def _finding(
    rule_id: str = "R1", path: str = "app.py", line: int = 1, cwe: int | None = 89
) -> Finding:
    return Finding(
        rule_id=rule_id,
        title="t",
        message="m",
        cwe=cwe,
        locations=(SourceLocation(path=path, start_line=line),),
        provenance=Provenance(producer="test"),
    )


class TestFingerprintFor:
    def test_identical_findings_produce_the_same_fingerprint(self) -> None:
        a = _finding()
        b = _finding()
        assert fingerprint_for(a) == fingerprint_for(b)

    def test_different_rule_ids_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(rule_id="A")) != fingerprint_for(_finding(rule_id="B"))

    def test_different_paths_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(path="a.py")) != fingerprint_for(_finding(path="b.py"))

    def test_different_locations_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(line=1)) != fingerprint_for(_finding(line=2))

    def test_different_cwes_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(cwe=79)) != fingerprint_for(_finding(cwe=89))

    def test_no_cwe_and_a_cwe_produce_different_fingerprints(self) -> None:
        assert fingerprint_for(_finding(cwe=None)) != fingerprint_for(_finding(cwe=89))

    def test_a_finding_with_no_location_does_not_crash(self) -> None:
        finding = Finding(
            rule_id="R1", title="t", message="m", provenance=Provenance(producer="test")
        )
        assert fingerprint_for(finding)

    def test_a_finding_with_no_location_is_stable(self) -> None:
        finding_a = Finding(
            rule_id="R1", title="t", message="m", provenance=Provenance(producer="test")
        )
        finding_b = Finding(
            rule_id="R1", title="t2", message="m2", provenance=Provenance(producer="other")
        )
        assert fingerprint_for(finding_a) == fingerprint_for(finding_b)

    def test_fingerprint_is_a_short_hex_string(self) -> None:
        fingerprint = fingerprint_for(_finding())
        assert len(fingerprint) == 16
        int(fingerprint, 16)  # raises ValueError if not valid hex
