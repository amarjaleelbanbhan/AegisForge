"""Unit tests for `apply_and_rescan` (MPS §16 Gates A/C).

Uses the real `git` binary and the real `BanditScanner` for the successful/
still-vulnerable cases, per this codebase's established preference for
exercising real components wherever the target is genuinely reachable —
this module's whole job is applying a real diff and re-running a real
scanner, so a fake scanner would test nothing meaningful about it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cortexward.agents import apply_and_rescan
from cortexward.domain import Finding, Patch, Provenance, SourceLocation
from cortexward.scanners import BanditScanner

pytestmark = pytest.mark.unit

_VULNERABLE_SOURCE = "import subprocess\n\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n"

_FIXING_DIFF = (
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,5 +1,5 @@\n"
    " import subprocess\n"
    " \n"
    " \n"
    " def run(cmd):\n"
    "-    subprocess.call(cmd, shell=True)\n"
    "+    subprocess.call(cmd, shell=False)\n"
)

_NON_FIXING_DIFF = (
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,5 +1,5 @@\n"
    " import subprocess\n"
    " \n"
    " \n"
    "-def run(cmd):\n"
    "+def run(cmd):  # unrelated comment\n"
    "     subprocess.call(cmd, shell=True)\n"
)

_MISMATCHED_DIFF = (
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,5 +1,5 @@\n"
    " import subprocess\n"
    " \n"
    " \n"
    " def run(cmd):\n"
    "-    subprocess.call(cmd, shell=THIS_CONTEXT_DOES_NOT_MATCH)\n"
    "+    subprocess.call(cmd, shell=False)\n"
)


def _finding(rule_id: str = "B602") -> Finding:
    return Finding(
        rule_id=rule_id,
        title="t",
        message="shell=True is dangerous",
        cwe=78,
        locations=(SourceLocation(path="app.py", start_line=5),),
        provenance=Provenance(producer="bandit"),
    )


def _patch(diff: str, files_changed: tuple[str, ...] = ("app.py",)) -> Patch:
    return Patch(
        finding_id="find_1",
        diff=diff,
        description="fix",
        files_changed=files_changed,
        provenance=Provenance(producer="repair"),
    )


class TestSuccessfulGate:
    def test_a_fixing_patch_returns_true(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        result = apply_and_rescan(
            _patch(_FIXING_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
            languages=("python",),
        )
        assert result is True

    def test_original_file_is_untouched(self, tmp_path: Path) -> None:
        source = tmp_path / "app.py"
        source.write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        apply_and_rescan(
            _patch(_FIXING_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
            languages=("python",),
        )
        assert source.read_text(encoding="utf-8") == _VULNERABLE_SOURCE

    def test_a_non_fixing_patch_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        result = apply_and_rescan(
            _patch(_NON_FIXING_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
            languages=("python",),
        )
        assert result is False


class TestInconclusiveOutcomes:
    def test_no_files_changed_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        result = apply_and_rescan(
            _patch(_FIXING_DIFF, files_changed=()),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None

    def test_a_diff_that_does_not_apply_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        result = apply_and_rescan(
            _patch(_MISMATCHED_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None

    def test_missing_source_file_returns_none(self, tmp_path: Path) -> None:
        result = apply_and_rescan(
            _patch(_FIXING_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None

    def test_git_not_available_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        result = apply_and_rescan(
            _patch(_FIXING_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None

    def test_a_hung_git_apply_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same inconclusive treatment as git being unavailable at all --
        # a timed-out `git apply` must not propagate TimeoutExpired and
        # crash gate verification.
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")

        def _timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=["git", "apply"], timeout=30)

        monkeypatch.setattr(subprocess, "run", _timeout)
        result = apply_and_rescan(
            _patch(_FIXING_DIFF),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None

    @pytest.mark.parametrize(
        "unsafe_path",
        [
            "../evil.py",
            "/etc/passwd",
            "C:/evil.py",
            "sub/../../evil.py",
            "",
        ],
    )
    def test_unsafe_relative_paths_return_none(self, tmp_path: Path, unsafe_path: str) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        result = apply_and_rescan(
            _patch(_FIXING_DIFF, files_changed=(unsafe_path,)),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None

    def test_windows_style_traversal_is_also_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        result = apply_and_rescan(
            _patch(_FIXING_DIFF, files_changed=("..\\evil.py",)),
            _finding(),
            root=tmp_path,
            scanners=(BanditScanner(),),
        )
        assert result is None
