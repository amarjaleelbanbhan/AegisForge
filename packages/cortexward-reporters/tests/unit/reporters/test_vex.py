"""Unit tests for the CycloneDX VEX reporter."""

from __future__ import annotations

import json

import pytest

from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingState,
    Provenance,
    Severity,
    SourceLocation,
    VerificationRung,
)
from cortexward.ports import ReporterPort
from cortexward.reporters import CycloneDxVexReporter

pytestmark = pytest.mark.unit


def _finding(
    rule_id: str = "B602",
    title: str = "bandit: B602",
    message: str = "shell=True is dangerous",
    severity: Severity = Severity.HIGH,
    cwe: int | None = 78,
    locations: tuple[SourceLocation, ...] = (SourceLocation(path="app.py", start_line=4),),
    evidence: tuple[Evidence, ...] = (),
    state: FindingState = FindingState.CANDIDATE,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        title=title,
        message=message,
        severity=severity,
        cwe=cwe,
        locations=locations,
        evidence=evidence,
        state=state,
        provenance=Provenance(producer="bandit"),
    )


class TestProtocolConformance:
    def test_reporter_satisfies_the_port(self) -> None:
        assert isinstance(CycloneDxVexReporter(), ReporterPort)

    def test_format_id_is_cyclonedx_vex(self) -> None:
        assert CycloneDxVexReporter().format_id == "cyclonedx-vex"


class TestRenderShape:
    def test_media_type_and_filename(self) -> None:
        artifact = CycloneDxVexReporter().render([])
        assert artifact.media_type == "application/vnd.cyclonedx+json"
        assert artifact.filename == "cortexward.vex.json"

    def test_content_is_valid_cyclonedx_document(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding()])
        document = json.loads(artifact.content)
        assert document["bomFormat"] == "CycloneDX"
        assert document["specVersion"] == "1.5"

    def test_empty_findings_produces_no_vulnerabilities(self) -> None:
        artifact = CycloneDxVexReporter().render([])
        document = json.loads(artifact.content)
        assert document["vulnerabilities"] == []

    def test_metadata_identifies_cortexward(self) -> None:
        artifact = CycloneDxVexReporter().render([])
        document = json.loads(artifact.content)
        tool = document["metadata"]["tools"][0]
        assert tool["name"] == "CortexWard"
        assert tool["version"]


class TestVulnerabilityMapping:
    def test_vulnerability_carries_rule_id_and_description(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding()])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["id"] == "B602"
        assert vuln["description"] == "shell=True is dangerous"

    def test_cwe_appears_when_present(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding(cwe=78)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["cwes"] == [78]

    def test_no_cwe_omits_the_cwes_field(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding(cwe=None)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert "cwes" not in vuln

    def test_affects_carries_every_location(self) -> None:
        locations = (
            SourceLocation(path="app.py", start_line=4),
            SourceLocation(path="lib.py", start_line=9),
        )
        artifact = CycloneDxVexReporter().render([_finding(locations=locations)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        refs = [affect["ref"] for affect in vuln["affects"]]
        assert refs == ["cortexward:app.py", "cortexward:lib.py"]

    @pytest.mark.parametrize(
        ("severity", "expected_rating"),
        [
            (Severity.CRITICAL, "critical"),
            (Severity.HIGH, "high"),
            (Severity.MEDIUM, "medium"),
            (Severity.LOW, "low"),
            (Severity.INFO, "info"),
        ],
    )
    def test_severity_maps_to_the_expected_rating(
        self, severity: Severity, expected_rating: str
    ) -> None:
        artifact = CycloneDxVexReporter().render([_finding(severity=severity)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["ratings"][0]["severity"] == expected_rating


class TestAnalysisState:
    def test_candidate_with_no_evidence_is_in_triage(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding(state=FindingState.CANDIDATE)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["analysis"]["state"] == "in_triage"

    def test_patched_finding_is_resolved(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding(state=FindingState.PATCHED)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["analysis"]["state"] == "resolved"

    def test_strong_independent_evidence_is_exploitable(self) -> None:
        evidence = (
            Evidence(
                kind=EvidenceKind.EXPLOIT_POC,
                rung=VerificationRung.DYNAMIC_POC,
                summary="PoC succeeded",
                supports=True,
                provenance=Provenance(producer="sandbox"),
            ),
        )
        artifact = CycloneDxVexReporter().render([_finding(evidence=evidence)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["analysis"]["state"] == "exploitable"

    def test_refuting_evidence_is_not_affected(self) -> None:
        evidence = (
            Evidence(
                kind=EvidenceKind.REFUTATION,
                rung=VerificationRung.NONE,
                summary="Proven unreachable",
                supports=False,
                provenance=Provenance(producer="verifier"),
            ),
        )
        artifact = CycloneDxVexReporter().render([_finding(evidence=evidence)])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert vuln["analysis"]["state"] == "not_affected"

    def test_analysis_detail_carries_the_assessment_rationale(self) -> None:
        artifact = CycloneDxVexReporter().render([_finding()])
        (vuln,) = json.loads(artifact.content)["vulnerabilities"]
        assert "evidence item(s)" in vuln["analysis"]["detail"]
