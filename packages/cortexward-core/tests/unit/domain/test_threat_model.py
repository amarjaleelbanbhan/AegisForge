"""Unit tests for STRIDE threat-model classification (`cortexward.domain.threat_model`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cortexward.domain import Severity, SourceLocation, StrideCategory, Threat, ThreatModel
from cortexward.domain.threat_model import stride_categories_for

pytestmark = pytest.mark.unit


class TestStrideCategoriesFor:
    def test_none_cwe_yields_no_categories(self) -> None:
        assert stride_categories_for(None) == frozenset()

    def test_unmapped_cwe_yields_no_categories(self) -> None:
        assert stride_categories_for(999_999) == frozenset()

    def test_sql_injection_maps_to_tampering_and_information_disclosure(self) -> None:
        categories = stride_categories_for(89)
        assert categories == {
            StrideCategory.TAMPERING,
            StrideCategory.INFORMATION_DISCLOSURE,
        }

    def test_hardcoded_credentials_maps_to_spoofing(self) -> None:
        assert stride_categories_for(798) == {StrideCategory.SPOOFING}

    def test_resource_consumption_maps_to_denial_of_service(self) -> None:
        assert stride_categories_for(400) == {StrideCategory.DENIAL_OF_SERVICE}

    def test_os_command_injection_maps_to_tampering_and_elevation(self) -> None:
        assert stride_categories_for(78) == {
            StrideCategory.TAMPERING,
            StrideCategory.ELEVATION_OF_PRIVILEGE,
        }

    def test_signature_verification_bypass_maps_to_spoofing_and_tampering(self) -> None:
        assert stride_categories_for(347) == {
            StrideCategory.SPOOFING,
            StrideCategory.TAMPERING,
        }


class TestThreat:
    def test_requires_at_least_one_category(self) -> None:
        with pytest.raises(ValidationError):
            Threat(
                finding_id="find_1",
                rule_id="B602",
                cwe=78,
                categories=frozenset(),
                severity=Severity.HIGH,
            )

    def test_defaults_to_not_reachable_and_no_location(self) -> None:
        threat = Threat(
            finding_id="find_1",
            rule_id="B602",
            cwe=78,
            categories=frozenset({StrideCategory.TAMPERING}),
            severity=Severity.HIGH,
        )
        assert threat.reachable_from_entrypoint is False
        assert threat.location is None

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            Threat(
                finding_id="find_1",
                rule_id="B602",
                cwe=78,
                categories=frozenset({StrideCategory.TAMPERING}),
                severity=Severity.HIGH,
                nonsense="x",  # type: ignore[call-arg]
            )

    def test_is_frozen(self) -> None:
        threat = Threat(
            finding_id="find_1",
            rule_id="B602",
            cwe=78,
            categories=frozenset({StrideCategory.TAMPERING}),
            severity=Severity.HIGH,
        )
        with pytest.raises(ValidationError):
            threat.severity = Severity.LOW  # type: ignore[misc]


def _threat(
    *,
    finding_id: str = "find_1",
    categories: frozenset[StrideCategory] = frozenset({StrideCategory.TAMPERING}),
    reachable: bool = False,
) -> Threat:
    return Threat(
        finding_id=finding_id,
        rule_id="B602",
        cwe=78,
        categories=categories,
        severity=Severity.HIGH,
        location=SourceLocation(path="app.py", start_line=1),
        reachable_from_entrypoint=reachable,
    )


class TestThreatModel:
    def test_defaults_to_no_threats(self) -> None:
        model = ThreatModel()
        assert model.threats == ()
        assert model.exposed == ()

    def test_by_category_filters_to_matching_threats_only(self) -> None:
        spoofing = _threat(finding_id="find_spoof", categories=frozenset({StrideCategory.SPOOFING}))
        tampering = _threat(
            finding_id="find_tamper", categories=frozenset({StrideCategory.TAMPERING})
        )
        model = ThreatModel(threats=(spoofing, tampering))
        assert model.by_category(StrideCategory.SPOOFING) == (spoofing,)
        assert model.by_category(StrideCategory.TAMPERING) == (tampering,)
        assert model.by_category(StrideCategory.DENIAL_OF_SERVICE) == ()

    def test_exposed_returns_only_reachable_threats(self) -> None:
        exposed = _threat(finding_id="find_exposed", reachable=True)
        not_exposed = _threat(finding_id="find_hidden", reachable=False)
        model = ThreatModel(threats=(exposed, not_exposed))
        assert model.exposed == (exposed,)

    def test_generated_at_defaults_to_now(self) -> None:
        model = ThreatModel()
        assert model.generated_at is not None
