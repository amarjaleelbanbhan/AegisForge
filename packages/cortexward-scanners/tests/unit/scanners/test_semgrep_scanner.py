"""Unit tests for the Semgrep scanner adapter.

Runs the real `semgrep` binary against fixture files written to `tmp_path`
-- no mocking of the subprocess or its JSON output for the scanning tests,
matching every other scanner adapter in this package. Each bundled rule is
exercised against both a vulnerable fixture (must fire) and a
semantically-equivalent safe fixture (must not fire), the same way the
rules themselves were verified while being authored.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cortexward.ports import ScannerPort
from cortexward.scanners import SemgrepScanner
from cortexward.scanners.semgrep_scanner import (
    _cwe_from_metadata,
    _rule_id_from_check_id,
    _rules_dir,
)

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestProtocolConformance:
    def test_satisfies_the_scanner_port(self) -> None:
        assert isinstance(SemgrepScanner(), ScannerPort)

    def test_name_is_semgrep(self) -> None:
        assert SemgrepScanner().name == "semgrep"


class TestBundledRules:
    """Every bundled rule fires on a real vulnerable fixture and stays
    silent on a real, semantically-equivalent safe one."""

    def test_ssrf_rule_fires_on_flask_request_value_reaching_requests_get(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            "app.py",
            "import requests\nfrom flask import request\n\n"
            "def fetch():\n    url = request.args.get('url')\n    return requests.get(url)\n",
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        ssrf_rule_id = "cortexward-ssrf-flask-request-to-outbound-call"
        ssrf = [f for f in findings if f.rule_id == ssrf_rule_id]
        assert len(ssrf) == 1
        assert ssrf[0].cwe == 918
        assert ssrf[0].severity_hint == "high"

    def test_ssrf_rule_is_silent_on_a_fixed_outbound_url(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "app.py",
            "import requests\n\ndef fetch():\n"
            "    return requests.get('https://api.example.com/status')\n",
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        ssrf_rule_id = "cortexward-ssrf-flask-request-to-outbound-call"
        assert not any(f.rule_id == ssrf_rule_id for f in findings)

    def test_ssti_rule_fires_on_render_template_string_with_interpolated_request_value(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            "app.py",
            "from flask import request, render_template_string\n\n"
            "def greet():\n    name = request.args.get('name')\n"
            "    return render_template_string(f'<h1>Hello {name}</h1>')\n",
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        ssti = [f for f in findings if f.rule_id == "cortexward-ssti-flask-render-template-string"]
        assert len(ssti) == 1
        assert ssti[0].cwe == 79

    def test_ssti_rule_is_silent_on_proper_jinja_variable_binding(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "app.py",
            "from flask import render_template_string\n\ndef greet():\n"
            "    return render_template_string('<h1>Hello {{ name }}</h1>', name='world')\n",
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        ssti_rule_id = "cortexward-ssti-flask-render-template-string"
        assert not any(f.rule_id == ssti_rule_id for f in findings)

    def test_hardcoded_credential_rule_fires_on_a_password_literal(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'password = "hunter2CorrectHorse"\n')
        findings = list(SemgrepScanner().scan(tmp_path))
        creds = [f for f in findings if f.rule_id == "cortexward-hardcoded-credential-assignment"]
        assert len(creds) == 1
        assert creds[0].cwe == 798

    def test_hardcoded_credential_rule_is_silent_on_an_env_var_read(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "config.py",
            'import os\npassword = os.environ["DB_PASSWORD"]\nusername = "admin"\n',
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        assert not any(f.rule_id == "cortexward-hardcoded-credential-assignment" for f in findings)

    def test_jwt_rule_fires_on_disabled_signature_verification(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "auth.py",
            "import jwt\n\ndef check(token):\n"
            '    return jwt.decode(token, options={"verify_signature": False})\n',
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        jwt_findings = [
            f for f in findings if f.rule_id == "cortexward-jwt-signature-verification-disabled"
        ]
        assert len(jwt_findings) == 1
        assert jwt_findings[0].cwe == 347
        assert jwt_findings[0].severity_hint == "high"

    def test_jwt_rule_is_silent_on_a_verified_decode(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "auth.py",
            "import jwt\n\ndef check(token, key):\n"
            '    return jwt.decode(token, key, algorithms=["HS256"])\n',
        )
        findings = list(SemgrepScanner().scan(tmp_path))
        assert not any(
            f.rule_id == "cortexward-jwt-signature-verification-disabled" for f in findings
        )


class TestScanning:
    def test_clean_code_yields_no_findings(self, tmp_path: Path) -> None:
        _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_empty_directory_yields_no_findings(self, tmp_path: Path) -> None:
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_finding_location_path_is_relative_to_root(self, tmp_path: Path) -> None:
        _write(tmp_path / "pkg", "config.py", 'password = "hunter2CorrectHorse"\n')
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings
        for finding in findings:
            assert not Path(finding.location.path).is_absolute()
            assert Path(finding.location.path).as_posix() == "pkg/config.py"

    def test_excluded_directories_are_not_scanned(self, tmp_path: Path) -> None:
        vendored = tmp_path / ".venv" / "site-packages"
        _write(vendored, "config.py", 'password = "hunter2CorrectHorse"\n')
        _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_languages_filter_excludes_non_python_scans(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'password = "hunter2CorrectHorse"\n')
        findings = list(SemgrepScanner().scan(tmp_path, languages=("javascript",)))
        assert findings == []

    def test_languages_filter_including_python_still_scans(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'password = "hunter2CorrectHorse"\n')
        findings = list(SemgrepScanner().scan(tmp_path, languages=("python", "javascript")))
        assert findings != []

    def test_raw_preserves_the_full_check_id(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'password = "hunter2CorrectHorse"\n')
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings
        assert "check_id" in findings[0].raw
        assert findings[0].raw["check_id"].endswith("cortexward-hardcoded-credential-assignment")

    def test_a_hung_subprocess_degrades_to_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=["semgrep"], timeout=300)

        monkeypatch.setattr(subprocess, "run", _timeout)
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_empty_subprocess_stdout_yields_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _empty_result(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _empty_result)
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_missing_semgrep_binary_degrades_to_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        _write(tmp_path, "config.py", 'password = "hunter2CorrectHorse"\n')
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_a_malformed_result_entry_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_result(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    '{"results": [null, "not an object", {"check_id": "x.y.z"}, '
                    '{"check_id": "a.b.c", "path": "app.py"}]}'
                ),
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", _fake_result)
        findings = list(SemgrepScanner().scan(tmp_path))
        assert len(findings) == 1
        assert findings[0].rule_id == "c"

    def test_a_result_dict_with_no_check_id_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_result(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"results": [{"path": "app.py"}, {"check_id": 123, "path": "app.py"}]}',
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", _fake_result)
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []

    def test_a_result_with_no_path_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_result(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"results": [{"check_id": "x.y.z"}]}',
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", _fake_result)
        findings = list(SemgrepScanner().scan(tmp_path))
        assert findings == []


class TestPrivateHelpers:
    def test_rules_dir_exists_and_contains_the_bundled_rule_files(self) -> None:
        rules_dir = _rules_dir()
        assert rules_dir.is_dir()
        names = {p.name for p in rules_dir.iterdir()}
        assert names == {
            "ssrf.yml",
            "template_injection.yml",
            "hardcoded_credentials.yml",
            "jwt_signature_bypass.yml",
        }

    def test_rule_id_strips_the_directory_path_prefix(self) -> None:
        assert (
            _rule_id_from_check_id("packages.cortexward-scanners.semgrep_rules.my-rule-id")
            == "my-rule-id"
        )

    def test_rule_id_with_no_prefix_is_unchanged(self) -> None:
        assert _rule_id_from_check_id("my-rule-id") == "my-rule-id"

    def test_cwe_from_metadata_parses_the_project_convention(self) -> None:
        assert _cwe_from_metadata({"cwe": "CWE-798: Use of Hard-coded Credentials"}) == 798

    def test_cwe_from_metadata_returns_none_when_absent(self) -> None:
        assert _cwe_from_metadata({}) is None

    def test_cwe_from_metadata_returns_none_when_metadata_is_not_a_dict(self) -> None:
        assert _cwe_from_metadata(None) is None
        assert _cwe_from_metadata("not a dict") is None

    def test_cwe_from_metadata_returns_none_for_a_malformed_cwe_field(self) -> None:
        assert _cwe_from_metadata({"cwe": "not-a-cwe-string"}) is None
        assert _cwe_from_metadata({"cwe": 798}) is None
