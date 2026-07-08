"""Unit tests for RawFinding -> Finding normalization and cross-tool correlation."""

from __future__ import annotations

import pytest

from cortexward.domain import EvidenceKind, Severity, SourceLocation, VerificationRung
from cortexward.ports import RawFinding
from cortexward.scanners import correlate, normalize

pytestmark = pytest.mark.unit


def _raw(
    rule_id: str = "B602",
    message: str = "shell=True is dangerous",
    path: str = "app.py",
    line: int = 4,
    severity_hint: str | None = "HIGH",
    cwe: int | None = 78,
    raw: dict[str, str] | None = None,
) -> RawFinding:
    return RawFinding(
        rule_id=rule_id,
        message=message,
        location=SourceLocation(path=path, start_line=line),
        severity_hint=severity_hint,
        cwe=cwe,
        raw=raw or {},
    )


class TestNormalize:
    def test_produces_a_finding_with_one_static_match_evidence(self) -> None:
        finding = normalize(_raw(), producer="bandit")
        assert finding.rule_id == "B602"
        assert finding.message == "shell=True is dangerous"
        assert finding.cwe == 78
        assert finding.locations == (SourceLocation(path="app.py", start_line=4),)
        assert len(finding.evidence) == 1
        evidence = finding.evidence[0]
        assert evidence.kind is EvidenceKind.STATIC_MATCH
        assert evidence.rung is VerificationRung.NONE
        assert evidence.supports is True
        assert evidence.provenance.producer == "bandit"

    def test_title_includes_the_producer_and_rule_id(self) -> None:
        finding = normalize(_raw(rule_id="B105"), producer="bandit")
        assert finding.title == "bandit: B105"

    def test_producer_is_recorded_as_a_tag(self) -> None:
        finding = normalize(_raw(), producer="bandit")
        assert "bandit" in finding.tags

    def test_raw_native_fields_flow_into_evidence_data(self) -> None:
        finding = normalize(_raw(raw={"test_name": "shell_injection"}), producer="bandit")
        assert finding.evidence[0].data == {"test_name": "shell_injection"}

    @pytest.mark.parametrize(
        ("hint", "expected"),
        [
            ("LOW", Severity.LOW),
            ("Medium", Severity.MEDIUM),
            ("high", Severity.HIGH),
            ("CRITICAL", Severity.CRITICAL),
            ("info", Severity.INFO),
            (None, Severity.MEDIUM),
            ("unrecognized-hint", Severity.MEDIUM),
        ],
    )
    def test_severity_hint_mapping(self, hint: str | None, expected: Severity) -> None:
        finding = normalize(_raw(severity_hint=hint), producer="bandit")
        assert finding.severity is expected


class TestCorrelate:
    def test_a_single_scanners_findings_pass_through_unmerged(self) -> None:
        findings = correlate(
            {"bandit": [_raw(rule_id="B602"), _raw(rule_id="B105", line=6, cwe=259)]}
        )
        assert len(findings) == 2

    def test_two_scanners_reporting_the_same_cwe_at_the_same_location_merge(self) -> None:
        bandit_finding = _raw(rule_id="B602", cwe=78, path="app.py", line=4)
        semgrep_finding = _raw(
            rule_id="python.lang.security.subprocess-shell-true", cwe=78, path="app.py", line=4
        )
        findings = correlate({"bandit": [bandit_finding], "semgrep": [semgrep_finding]})
        assert len(findings) == 1
        merged = findings[0]
        assert len(merged.evidence) == 2
        assert merged.tags == frozenset({"bandit", "semgrep"})

    def test_merge_keeps_the_worse_of_two_severities(self) -> None:
        low = _raw(rule_id="a", cwe=78, severity_hint="LOW")
        critical = _raw(rule_id="b", cwe=78, severity_hint="CRITICAL")
        findings = correlate({"tool-a": [low], "tool-b": [critical]})
        assert len(findings) == 1
        assert findings[0].severity is Severity.CRITICAL

    def test_merge_records_related_ids(self) -> None:
        first = _raw(rule_id="a", cwe=78)
        second = _raw(rule_id="b", cwe=78)
        findings = correlate({"tool-a": [first], "tool-b": [second]})
        assert len(findings) == 1
        assert len(findings[0].related_ids) == 1

    def test_findings_at_different_lines_do_not_merge(self) -> None:
        first = _raw(cwe=78, line=4)
        second = _raw(cwe=78, line=99)
        findings = correlate({"bandit": [first], "semgrep": [second]})
        assert len(findings) == 2

    def test_findings_with_different_cwes_do_not_merge(self) -> None:
        first = _raw(cwe=78, line=4)
        second = _raw(cwe=89, line=4)
        findings = correlate({"bandit": [first], "semgrep": [second]})
        assert len(findings) == 2

    def test_findings_with_no_cwe_never_merge_even_at_the_same_location(self) -> None:
        first = _raw(cwe=None, line=1, rule_id="Secret Keyword")
        second = _raw(cwe=None, line=1, rule_id="Secret Keyword")
        findings = correlate({"detect-secrets": [first, second]})
        assert len(findings) == 2

    def test_three_scanners_reporting_the_same_bug_merge_into_one(self) -> None:
        findings = correlate(
            {
                "bandit": [_raw(rule_id="B602", cwe=78)],
                "semgrep": [_raw(rule_id="subprocess-shell-true", cwe=78)],
                "codeql": [_raw(rule_id="py/command-injection", cwe=78)],
            }
        )
        assert len(findings) == 1
        assert len(findings[0].evidence) == 3
        assert findings[0].tags == frozenset({"bandit", "semgrep", "codeql"})

    def test_empty_results_yield_no_findings(self) -> None:
        assert correlate({}) == []

    def test_a_scanner_with_no_findings_contributes_nothing(self) -> None:
        assert correlate({"bandit": []}) == []
