"""Unit tests for the detect-secrets scanner adapter.

Runs the real `detect-secrets` package against fixture files written to
`tmp_path` — no mocking, since the whole point of this adapter is correctly
invoking and parsing a real detector library.

Fake secret values are built by concatenating string halves rather than
written as a single literal, so this source file itself never contains a
contiguous, real-looking token — the same secret text this adapter is meant
to catch would otherwise trip this repo's own gitleaks self-audit (CI) on
this very file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cortexward.ports import ScannerPort
from cortexward.scanners import SecretsScanner
from cortexward.scanners.secrets_scanner import _finding_from_secret

pytestmark = pytest.mark.unit

_FAKE_GITHUB_TOKEN = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyzAB"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _symlinks_supported() -> bool:
    """Whether this process can create symlinks (needs Developer Mode or
    admin on Windows; unprivileged elsewhere)."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "target"
        target.write_text("x", encoding="utf-8")
        try:
            os.symlink(target, Path(td) / "link")
        except OSError:
            return False
    return True


_HAS_SYMLINKS = _symlinks_supported()


class TestProtocolConformance:
    def test_secrets_scanner_satisfies_the_port(self) -> None:
        assert isinstance(SecretsScanner(), ScannerPort)

    def test_name_is_detect_secrets(self) -> None:
        assert SecretsScanner().name == "detect-secrets"


class TestScanning:
    def test_finds_a_known_secret_pattern(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", f'github_token = "{_FAKE_GITHUB_TOKEN}"\n')
        findings = list(SecretsScanner().scan(tmp_path))
        github_findings = [f for f in findings if f.rule_id == "GitHub Token"]
        assert len(github_findings) == 1
        finding = github_findings[0]
        assert finding.location.path == "config.py"
        assert finding.location.start_line == 1
        assert finding.severity_hint == "CRITICAL"
        assert finding.cwe == 798

    def test_clean_code_yields_no_findings(self, tmp_path: Path) -> None:
        _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
        findings = list(SecretsScanner().scan(tmp_path))
        assert findings == []

    def test_raw_carries_a_hash_never_the_secret_itself(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", f'github_token = "{_FAKE_GITHUB_TOKEN}"\n')
        findings = list(SecretsScanner().scan(tmp_path))
        assert findings
        for finding in findings:
            assert "hashed_secret" in finding.raw
            assert _FAKE_GITHUB_TOKEN not in finding.raw["hashed_secret"]
            assert _FAKE_GITHUB_TOKEN not in finding.message

    def test_scans_non_python_files_too(self, tmp_path: Path) -> None:
        # Secrets aren't Python-specific; a .env file must be scanned too.
        _write(tmp_path, ".env", f"GITHUB_TOKEN={_FAKE_GITHUB_TOKEN}\n")
        findings = list(SecretsScanner().scan(tmp_path))
        assert any(f.location.path == ".env" for f in findings)

    def test_languages_filter_is_ignored(self, tmp_path: Path) -> None:
        # Secrets scanning is language-agnostic; even an explicit non-Python
        # languages filter must not suppress results.
        _write(tmp_path, "config.py", f'github_token = "{_FAKE_GITHUB_TOKEN}"\n')
        findings = list(SecretsScanner().scan(tmp_path, languages=("javascript",)))
        assert findings != []

    def test_excluded_directories_are_not_scanned(self, tmp_path: Path) -> None:
        _write(
            tmp_path / ".venv" / "site-packages", "vendored.py", f'token = "{_FAKE_GITHUB_TOKEN}"\n'
        )
        findings = list(SecretsScanner().scan(tmp_path))
        assert findings == []

    def test_binary_files_do_not_crash_the_scan(self, tmp_path: Path) -> None:
        (tmp_path / "image.bin").write_bytes(bytes(range(256)))
        findings = list(SecretsScanner().scan(tmp_path))
        assert findings == []

    def test_empty_directory_yields_no_findings(self, tmp_path: Path) -> None:
        findings = list(SecretsScanner().scan(tmp_path))
        assert findings == []

    @pytest.mark.skipif(not _HAS_SYMLINKS, reason="symlinks not supported in this environment")
    def test_a_symlinked_file_inside_root_is_not_scanned(self, tmp_path: Path) -> None:
        # A malicious/crafted repository is untrusted input (ADR-0004): a
        # symlink inside the scanned root pointing at a real secret file
        # elsewhere on disk must not be followed into the scan.
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside_secret.py"
            outside.write_text(f'token = "{_FAKE_GITHUB_TOKEN}"\n', encoding="utf-8")
            (tmp_path / "link.py").symlink_to(outside)
            findings = list(SecretsScanner().scan(tmp_path))
        assert findings == []

    @pytest.mark.skipif(not _HAS_SYMLINKS, reason="symlinks not supported in this environment")
    def test_a_symlinked_directory_inside_root_is_not_traversed(self, tmp_path: Path) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            _write(Path(outside_dir), "secret.py", f'token = "{_FAKE_GITHUB_TOKEN}"\n')
            (tmp_path / "linked_dir").symlink_to(outside_dir, target_is_directory=True)
            findings = list(SecretsScanner().scan(tmp_path))
        assert findings == []


class TestPrivateHelpers:
    def test_finding_from_secret_falls_back_to_the_raw_filename_outside_root(self) -> None:
        secret = {
            "filename": "/completely/unrelated/path.py",
            "line_number": 1,
            "type": "GitHub Token",
            "hashed_secret": "abc123",
        }
        finding = _finding_from_secret(secret, root=Path("/some/other/root"))
        assert finding.location.path == str(Path("/completely/unrelated/path.py"))
