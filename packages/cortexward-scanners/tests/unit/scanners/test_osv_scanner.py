"""Unit tests for the OSV.dev dependency-vulnerability scanner.

Runs real queries against the public OSV.dev API — no mocking, since the
whole point of this adapter is correctly querying and parsing a real
external service. `requests==2.6.0` is used as a stable, long-fixed,
guaranteed-vulnerable fixture (multiple public GHSA advisories exist for
it and are not expected to disappear).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from cortexward.ports import ScannerPort
from cortexward.scanners import OsvScanner
from cortexward.scanners import osv_scanner as osv_scanner_module
from cortexward.scanners.osv_scanner import _fetch_summary, _find_pins

pytestmark = [pytest.mark.unit, pytest.mark.integration]

_KNOWN_VULNERABLE_PIN = "requests==2.6.0"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestProtocolConformance:
    def test_osv_scanner_satisfies_the_port(self) -> None:
        assert isinstance(OsvScanner(), ScannerPort)

    def test_name_is_osv(self) -> None:
        assert OsvScanner().name == "osv"


class TestPinExtraction:
    def test_extracts_an_exact_pin_from_requirements_txt(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", "requests==2.6.0\n")
        pins = _find_pins(tmp_path)
        assert pins == {("requests", "2.6.0"): "requirements.txt"}

    def test_skips_range_constraints(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", "click>=8.0\nrequests~=2.0\n")
        assert _find_pins(tmp_path) == {}

    def test_requirements_dev_txt_pins_are_included(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements-dev.txt", "pytest==7.0.0\n")
        pins = _find_pins(tmp_path)
        assert pins == {("pytest", "7.0.0"): "requirements-dev.txt"}

    def test_extracts_an_exact_pin_from_pyproject_toml(self, tmp_path: Path) -> None:
        _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests==2.6.0"]\n')
        pins = _find_pins(tmp_path)
        assert pins == {("requests", "2.6.0"): "pyproject.toml"}

    def test_pyproject_toml_range_constraints_are_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests>=2.0"]\n')
        assert _find_pins(tmp_path) == {}

    def test_malformed_pyproject_toml_yields_no_pins(self, tmp_path: Path) -> None:
        _write(tmp_path, "pyproject.toml", "not valid [ toml\n")
        assert _find_pins(tmp_path) == {}

    def test_pyproject_toml_with_no_project_table_yields_no_pins(self, tmp_path: Path) -> None:
        _write(tmp_path, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        assert _find_pins(tmp_path) == {}

    def test_pyproject_toml_with_no_dependencies_key_yields_no_pins(self, tmp_path: Path) -> None:
        _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\n')
        assert _find_pins(tmp_path) == {}

    def test_pyproject_toml_non_string_dependency_entry_is_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "pyproject.toml", '[project]\ndependencies = [123, "requests==2.6.0"]\n')
        pins = _find_pins(tmp_path)
        assert pins == {("requests", "2.6.0"): "pyproject.toml"}

    def test_no_manifests_yields_no_pins(self, tmp_path: Path) -> None:
        assert _find_pins(tmp_path) == {}

    def test_same_pin_in_two_manifests_is_deduplicated(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", "requests==2.6.0\n")
        _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests==2.6.0"]\n')
        pins = _find_pins(tmp_path)
        assert len(pins) == 1


class TestScanning:
    def test_finds_known_vulnerabilities_for_an_old_pinned_version(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", f"{_KNOWN_VULNERABLE_PIN}\n")
        findings = list(OsvScanner().scan(tmp_path))
        assert findings
        for finding in findings:
            assert finding.location.path == "requirements.txt"
            assert "requests==2.6.0" in finding.message
            assert finding.raw["package"] == "requests"
            assert finding.raw["version"] == "2.6.0"

    def test_unpinned_dependencies_produce_no_findings(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", "requests>=2.0\n")
        findings = list(OsvScanner().scan(tmp_path))
        assert findings == []

    def test_no_manifests_produces_no_findings(self, tmp_path: Path) -> None:
        findings = list(OsvScanner().scan(tmp_path))
        assert findings == []

    def test_languages_filter_excludes_non_python_scans(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", f"{_KNOWN_VULNERABLE_PIN}\n")
        findings = list(OsvScanner().scan(tmp_path, languages=("javascript",)))
        assert findings == []

    def test_languages_filter_including_python_still_scans(self, tmp_path: Path) -> None:
        _write(tmp_path, "requirements.txt", f"{_KNOWN_VULNERABLE_PIN}\n")
        findings = list(OsvScanner().scan(tmp_path, languages=("python", "javascript")))
        assert findings != []

    def test_a_clean_recent_pin_produces_no_findings(self, tmp_path: Path) -> None:
        # A package name that has never existed on PyPI: OSV returns an
        # empty vulns list for it rather than erroring.
        _write(tmp_path, "requirements.txt", "cortexward-definitely-not-a-real-package==1.0.0\n")
        findings = list(OsvScanner().scan(tmp_path))
        assert findings == []

    def test_a_batch_query_failure_degrades_to_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "requirements.txt", f"{_KNOWN_VULNERABLE_PIN}\n")

        def _raise(*_args: object, **_kwargs: object) -> list[list[str]]:
            raise TimeoutError

        monkeypatch.setattr(osv_scanner_module, "_query_vulnerable_ids", _raise)
        findings = list(OsvScanner().scan(tmp_path))
        assert findings == []

    def test_a_repeated_vulnerability_id_only_fetches_its_summary_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "requirements.txt", "foo==1.0.0\nbar==1.0.0\n")
        call_count = 0

        def _fake_query(pins: Sequence[object]) -> list[list[str]]:
            return [["SHARED-ID"] for _ in pins]

        def _fake_fetch(vuln_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"summary for {vuln_id}"

        monkeypatch.setattr(osv_scanner_module, "_query_vulnerable_ids", _fake_query)
        monkeypatch.setattr(osv_scanner_module, "_fetch_summary", _fake_fetch)
        findings = list(OsvScanner().scan(tmp_path))
        assert len(findings) == 2
        assert call_count == 1


class TestFetchSummary:
    def test_network_failure_falls_back_to_a_generic_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise TimeoutError

        monkeypatch.setattr(osv_scanner_module, "_get_json", _raise)
        assert _fetch_summary("FAKE-ID") == "Known vulnerability FAKE-ID"
