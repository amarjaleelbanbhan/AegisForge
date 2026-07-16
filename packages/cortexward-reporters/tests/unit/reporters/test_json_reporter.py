"""Unit tests for CortexWard's own JSON export reporter."""

from __future__ import annotations

import json

import pytest

from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    Provenance,
    Severity,
    SourceLocation,
    VerificationRung,
)
from cortexward.ports import ReporterPort
from cortexward.reporters import JsonReporter

pytestmark = pytest.mark.unit


def _finding(
    rule_id: str = "B602",
    title: str = "bandit: B602",
    message: str = "shell=True is dangerous",
    severity: Severity = Severity.HIGH,
    cwe: int | None = 78,
    locations: tuple[SourceLocation, ...] = (SourceLocation(path="app.py", start_line=4),),
    evidence: tuple[Evidence, ...] = (),
) -> Finding:
    return Finding(
        rule_id=rule_id,
        title=title,
        message=message,
        severity=severity,
        cwe=cwe,
        locations=locations,
        provenance=Provenance(producer="bandit"),
        evidence=evidence,
    )


class TestProtocolConformance:
    def test_json_reporter_satisfies_the_port(self) -> None:
        assert isinstance(JsonReporter(), ReporterPort)

    def test_format_id_is_cortexward_json(self) -> None:
        assert JsonReporter().format_id == "cortexward-json"


class TestRenderShape:
    def test_media_type_and_filename(self) -> None:
        artifact = JsonReporter().render([])
        assert artifact.media_type == "application/json"
        assert artifact.filename == "cortexward.json"

    def test_content_is_valid_json(self) -> None:
        artifact = JsonReporter().render([_finding()])
        document = json.loads(artifact.content)
        assert "cortexward_version" in document
        assert document["cortexward_version"]

    def test_empty_findings_produces_an_empty_list(self) -> None:
        artifact = JsonReporter().render([])
        document = json.loads(artifact.content)
        assert document["findings"] == []


class TestFindingFidelity:
    def test_basic_fields_round_trip(self) -> None:
        artifact = JsonReporter().render([_finding()])
        (finding_json,) = json.loads(artifact.content)["findings"]
        assert finding_json["rule_id"] == "B602"
        assert finding_json["title"] == "bandit: B602"
        assert finding_json["message"] == "shell=True is dangerous"
        assert finding_json["cwe"] == 78
        assert finding_json["severity"] == Severity.HIGH.value
        assert finding_json["state"] == "candidate"

    def test_locations_round_trip(self) -> None:
        locations = (
            SourceLocation(path="app.py", start_line=4, end_line=6, end_col=10),
            SourceLocation(path="lib.py", start_line=9),
        )
        artifact = JsonReporter().render([_finding(locations=locations)])
        (finding_json,) = json.loads(artifact.content)["findings"]
        assert [loc["path"] for loc in finding_json["locations"]] == ["app.py", "lib.py"]
        assert finding_json["locations"][0]["end_line"] == 6
        assert finding_json["locations"][0]["end_col"] == 10

    def test_evidence_survives_unlike_sarif(self) -> None:
        evidence = Evidence(
            kind=EvidenceKind.LLM_ASSESSMENT,
            supports=True,
            summary="matches known SQLi pattern",
            provenance=Provenance(producer="verifier", model="qwen2.5-coder:7b"),
        )
        artifact = JsonReporter().render([_finding(evidence=(evidence,))])
        (finding_json,) = json.loads(artifact.content)["findings"]
        (evidence_json,) = finding_json["evidence"]
        assert evidence_json["kind"] == "llm_assessment"
        assert evidence_json["summary"] == "matches known SQLi pattern"
        assert evidence_json["supports"] is True
        assert evidence_json["provenance"]["producer"] == "verifier"
        assert evidence_json["provenance"]["model"] == "qwen2.5-coder:7b"

    def test_reachability_evidence_rung_survives(self) -> None:
        evidence = Evidence(
            kind=EvidenceKind.REACHABILITY_PROOF,
            rung=VerificationRung.STATIC_REACHABILITY,
            supports=True,
            summary="reachable from 1 known entrypoint(s) via control flow",
            provenance=Provenance(producer="verifier"),
        )
        artifact = JsonReporter().render([_finding(evidence=(evidence,))])
        (finding_json,) = json.loads(artifact.content)["findings"]
        (evidence_json,) = finding_json["evidence"]
        assert evidence_json["kind"] == "reachability_proof"
        assert evidence_json["rung"] == VerificationRung.STATIC_REACHABILITY.value

    def test_multiple_findings_each_appear(self) -> None:
        findings = [_finding(rule_id="B602"), _finding(rule_id="B105")]
        artifact = JsonReporter().render(findings)
        document = json.loads(artifact.content)
        rule_ids = [f["rule_id"] for f in document["findings"]]
        assert rule_ids == ["B602", "B105"]

    def test_multiple_evidence_items_all_survive(self) -> None:
        evidence = (
            Evidence(
                kind=EvidenceKind.STATIC_MATCH,
                supports=True,
                summary="pattern match",
                provenance=Provenance(producer="bandit"),
            ),
            Evidence(
                kind=EvidenceKind.LLM_ASSESSMENT,
                supports=False,
                summary="looks like a false positive",
                provenance=Provenance(producer="verifier"),
            ),
        )
        artifact = JsonReporter().render([_finding(evidence=evidence)])
        (finding_json,) = json.loads(artifact.content)["findings"]
        assert len(finding_json["evidence"]) == 2
        assert {e["kind"] for e in finding_json["evidence"]} == {"static_match", "llm_assessment"}
