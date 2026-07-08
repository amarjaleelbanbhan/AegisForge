"""Unit tests for the SARIF 2.1.0 reporter."""

from __future__ import annotations

import json

import pytest

from cortexward.domain import Finding, Provenance, Severity, SourceLocation
from cortexward.ports import ReporterPort
from cortexward.reporters import SarifReporter

pytestmark = pytest.mark.unit


def _finding(
    rule_id: str = "B602",
    title: str = "bandit: B602",
    message: str = "shell=True is dangerous",
    severity: Severity = Severity.HIGH,
    cwe: int | None = 78,
    locations: tuple[SourceLocation, ...] = (SourceLocation(path="app.py", start_line=4),),
    tags: frozenset[str] = frozenset(),
) -> Finding:
    return Finding(
        rule_id=rule_id,
        title=title,
        message=message,
        severity=severity,
        cwe=cwe,
        locations=locations,
        provenance=Provenance(producer="bandit"),
        tags=tags,
    )


class TestProtocolConformance:
    def test_sarif_reporter_satisfies_the_port(self) -> None:
        assert isinstance(SarifReporter(), ReporterPort)

    def test_format_id_is_sarif(self) -> None:
        assert SarifReporter().format_id == "sarif"


class TestRenderShape:
    def test_media_type_and_filename(self) -> None:
        artifact = SarifReporter().render([])
        assert artifact.media_type == "application/sarif+json"
        assert artifact.filename == "cortexward.sarif"

    def test_content_is_valid_json(self) -> None:
        artifact = SarifReporter().render([_finding()])
        document = json.loads(artifact.content)
        assert document["version"] == "2.1.0"
        assert "$schema" in document

    def test_empty_findings_produces_one_run_with_no_results(self) -> None:
        artifact = SarifReporter().render([])
        document = json.loads(artifact.content)
        assert len(document["runs"]) == 1
        assert document["runs"][0]["results"] == []
        assert document["runs"][0]["tool"]["driver"]["rules"] == []

    def test_driver_identifies_cortexward(self) -> None:
        artifact = SarifReporter().render([])
        document = json.loads(artifact.content)
        driver = document["runs"][0]["tool"]["driver"]
        assert driver["name"] == "CortexWard"
        assert driver["informationUri"] == "https://github.com/amarjaleelbanbhan/CortexWard"
        assert driver["version"]


class TestResultMapping:
    def test_result_carries_rule_id_message_and_location(self) -> None:
        artifact = SarifReporter().render([_finding()])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        assert result["ruleId"] == "B602"
        assert result["message"]["text"] == "shell=True is dangerous"
        (location,) = result["locations"]
        physical = location["physicalLocation"]
        assert physical["artifactLocation"]["uri"] == "app.py"
        assert physical["region"]["startLine"] == 4

    def test_region_includes_end_line_and_column_when_present(self) -> None:
        location = SourceLocation(path="app.py", start_line=4, start_col=1, end_line=6, end_col=10)
        artifact = SarifReporter().render([_finding(locations=(location,))])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region["endLine"] == 6
        assert region["endColumn"] == 10

    def test_multiple_locations_all_appear(self) -> None:
        locations = (
            SourceLocation(path="app.py", start_line=4),
            SourceLocation(path="lib.py", start_line=9),
        )
        artifact = SarifReporter().render([_finding(locations=locations)])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        uris = [loc["physicalLocation"]["artifactLocation"]["uri"] for loc in result["locations"]]
        assert uris == ["app.py", "lib.py"]

    def test_cwe_appears_in_result_properties(self) -> None:
        artifact = SarifReporter().render([_finding(cwe=78)])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        assert result["properties"]["cwe"] == 78

    def test_no_cwe_omits_the_cwe_property(self) -> None:
        artifact = SarifReporter().render([_finding(cwe=None)])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        assert "cwe" not in result["properties"]

    def test_producer_tags_appear_in_result_properties(self) -> None:
        artifact = SarifReporter().render([_finding(tags=frozenset({"bandit", "semgrep"}))])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        assert result["properties"]["producers"] == ["bandit", "semgrep"]

    def test_state_appears_in_result_properties(self) -> None:
        artifact = SarifReporter().render([_finding()])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        assert result["properties"]["state"] == "candidate"

    @pytest.mark.parametrize(
        ("severity", "expected_level"),
        [
            (Severity.CRITICAL, "error"),
            (Severity.HIGH, "error"),
            (Severity.MEDIUM, "warning"),
            (Severity.LOW, "note"),
            (Severity.INFO, "note"),
        ],
    )
    def test_severity_maps_to_the_expected_sarif_level(
        self, severity: Severity, expected_level: str
    ) -> None:
        artifact = SarifReporter().render([_finding(severity=severity)])
        document = json.loads(artifact.content)
        (result,) = document["runs"][0]["results"]
        assert result["level"] == expected_level


class TestRuleDeduplication:
    def test_two_findings_with_the_same_rule_id_produce_one_rule(self) -> None:
        findings = [
            _finding(rule_id="B602"),
            _finding(rule_id="B602", locations=(SourceLocation(path="other.py", start_line=1),)),
        ]
        artifact = SarifReporter().render(findings)
        document = json.loads(artifact.content)
        rules = document["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 1
        assert len(document["runs"][0]["results"]) == 2

    def test_distinct_rule_ids_each_get_their_own_rule(self) -> None:
        findings = [_finding(rule_id="B602"), _finding(rule_id="B105")]
        artifact = SarifReporter().render(findings)
        document = json.loads(artifact.content)
        rule_ids = {rule["id"] for rule in document["runs"][0]["tool"]["driver"]["rules"]}
        assert rule_ids == {"B602", "B105"}

    def test_rule_includes_cwe_tag_when_present(self) -> None:
        artifact = SarifReporter().render([_finding(cwe=78)])
        document = json.loads(artifact.content)
        (rule,) = document["runs"][0]["tool"]["driver"]["rules"]
        assert rule["properties"]["cwe"] == 78
        assert "external/cwe/cwe-78" in rule["properties"]["tags"]

    def test_rule_omits_properties_when_no_cwe(self) -> None:
        artifact = SarifReporter().render([_finding(cwe=None)])
        document = json.loads(artifact.content)
        (rule,) = document["runs"][0]["tool"]["driver"]["rules"]
        assert "properties" not in rule
