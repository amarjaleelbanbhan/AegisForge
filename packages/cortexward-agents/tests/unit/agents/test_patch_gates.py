"""Unit tests for `apply_and_rescan` (MPS §16 Gates A/C).

Uses the real `git` binary and the real `BanditScanner` for the successful/
still-vulnerable cases, per this codebase's established preference for
exercising real components wherever the target is genuinely reachable —
this module's whole job is applying a real diff and re-running a real
scanner, so a fake scanner would test nothing meaningful about it.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from cortexward.agents import apply_and_rescan
from cortexward.agents.patch_gates import poc_neutralized
from cortexward.agents.patch_gates import tests_pass_in_sandbox as run_gate_b
from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    Patch,
    Provenance,
    SourceLocation,
    VerificationRung,
)
from cortexward.ports import ExecutionResult, ExecutionSpec
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


_MARKER = "CORTEXWARD_POC_gatetest"
_POC_CODE = "import importlib.util  # scripted poc\nprint('driving target')\n"

_NESTED_FIXING_DIFF = (
    "--- a/pkg/app.py\n"
    "+++ b/pkg/app.py\n"
    "@@ -1,5 +1,5 @@\n"
    " import subprocess\n"
    " \n"
    " \n"
    " def run(cmd):\n"
    "-    subprocess.call(cmd, shell=True)\n"
    "+    subprocess.call(cmd, shell=False)\n"
)


class _DictStore:
    """A get+put artifact store for gate tests (satisfies `ArtifactStore`)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_artifact(self, content: bytes) -> str:
        ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
        self.store[ref] = content
        return ref

    def get_artifact(self, ref: str) -> bytes:
        return self.store[ref]  # raises KeyError on an unknown ref


class _FakeSandbox:
    isolation_tier = "fake"

    def __init__(self, result: ExecutionResult | None = None, *, raises: bool = False) -> None:
        self._result = result
        self._raises = raises
        self.specs: list[ExecutionSpec] = []

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self.specs.append(spec)
        if self._raises:
            raise RuntimeError("docker daemon unreachable")
        assert self._result is not None
        return self._result


def _exec_result(
    *, exit_code: int = 0, stdout: str = "", timed_out: bool = False
) -> ExecutionResult:
    return ExecutionResult(
        exit_code=exit_code, stdout=stdout, stderr="", timed_out=timed_out, duration_seconds=0.1
    )


def _finding_with_poc(
    store: _DictStore,
    *,
    poc_path: str = "app.py",
    with_evidence: bool = True,
    ref: str | None = None,
    data: dict[str, str] | None = None,
) -> Finding:
    """A finding carrying an EXPLOIT_POC evidence whose PoC is stored in `store`."""
    evidence: tuple[Evidence, ...] = ()
    if with_evidence:
        poc_ref = ref if ref is not None else store.put_artifact(_POC_CODE.encode("utf-8"))
        evidence = (
            Evidence(
                kind=EvidenceKind.EXPLOIT_POC,
                rung=VerificationRung.DYNAMIC_POC,
                supports=True,
                summary="poc",
                provenance=Provenance(producer="poc"),
                artifact_ref=poc_ref,
                data=data if data is not None else {"poc_marker": _MARKER, "poc_path": poc_path},
            ),
        )
    return Finding(
        rule_id="B602",
        title="t",
        message="shell=True",
        cwe=78,
        locations=(SourceLocation(path="app.py", start_line=5),),
        evidence=evidence,
        provenance=Provenance(producer="bandit"),
    )


class TestGateDPocNeutralized:
    def test_patched_code_no_longer_triggers_is_neutralized(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store)
        # Patched code: the fake sandbox reports no marker -> exploit neutralized.
        sandbox = _FakeSandbox(_exec_result(stdout="nothing exploitable"))
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is True

    def test_patched_code_still_triggers_is_not_neutralized(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store)
        sandbox = _FakeSandbox(_exec_result(stdout=f"pwned {_MARKER}"))
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is False

    def test_no_poc_evidence_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store, with_evidence=False)
        sandbox = _FakeSandbox(_exec_result())
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None
        assert sandbox.specs == []

    def test_non_poc_evidence_is_ignored(self, tmp_path: Path) -> None:
        # A finding whose only evidence is not an EXPLOIT_POC yields no PoC to
        # re-run -> inconclusive (the evidence loop finds no match).
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = Finding(
            rule_id="B602",
            title="t",
            message="shell=True",
            cwe=78,
            locations=(SourceLocation(path="app.py", start_line=5),),
            evidence=(
                Evidence(
                    kind=EvidenceKind.LLM_ASSESSMENT,
                    supports=True,
                    summary="looks real",
                    provenance=Provenance(producer="verifier"),
                ),
            ),
            provenance=Provenance(producer="bandit"),
        )
        sandbox = _FakeSandbox(_exec_result())
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None

    def test_unknown_artifact_ref_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store, ref="sha256:missing")
        sandbox = _FakeSandbox(_exec_result())
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None

    def test_missing_marker_or_path_data_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store, data={"poc_path": "app.py"})  # no poc_marker
        sandbox = _FakeSandbox(_exec_result())
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None

    def test_unsafe_poc_path_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store, data={"poc_marker": _MARKER, "poc_path": "../evil.py"})
        sandbox = _FakeSandbox(_exec_result())
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None

    def test_patch_that_does_not_apply_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store)
        sandbox = _FakeSandbox(_exec_result(stdout="x"))
        result = poc_neutralized(
            _patch(_MISMATCHED_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None

    def test_sandbox_failure_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store)
        sandbox = _FakeSandbox(raises=True)
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None

    def test_unchanged_target_file_is_read_from_root(self, tmp_path: Path) -> None:
        # The patch touches app.py, but the PoC's target is a *different* file
        # present in the root: it's read from the original (branch coverage for
        # a patch that doesn't touch the vulnerable file -> still exploitable).
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        (tmp_path / "helper.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store, poc_path="helper.py")
        sandbox = _FakeSandbox(_exec_result(stdout=f"pwned {_MARKER}"))
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is False

    def test_target_file_missing_everywhere_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        store = _DictStore()
        finding = _finding_with_poc(store, poc_path="ghost.py")
        sandbox = _FakeSandbox(_exec_result(stdout="x"))
        result = poc_neutralized(
            _patch(_FIXING_DIFF), finding, root=tmp_path, sandbox=sandbox, artifacts=store
        )
        assert result is None


class TestGateBTestsPass:
    def test_pytest_exit_zero_is_pass(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(_exec_result(exit_code=0))
        result = run_gate_b(
            _patch(_FIXING_DIFF), root=tmp_path, sandbox=sandbox, artifacts=_DictStore()
        )
        assert result is True
        assert sandbox.specs[0].command == ("python", "-m", "pytest", "-q")

    def test_pytest_exit_one_is_fail(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(_exec_result(exit_code=1))
        result = run_gate_b(
            _patch(_FIXING_DIFF), root=tmp_path, sandbox=sandbox, artifacts=_DictStore()
        )
        assert result is False

    def test_no_tests_collected_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(_exec_result(exit_code=5))  # pytest: no tests collected
        result = run_gate_b(
            _patch(_FIXING_DIFF), root=tmp_path, sandbox=sandbox, artifacts=_DictStore()
        )
        assert result is None

    def test_timeout_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(_exec_result(exit_code=0, timed_out=True))
        result = run_gate_b(
            _patch(_FIXING_DIFF), root=tmp_path, sandbox=sandbox, artifacts=_DictStore()
        )
        assert result is None

    def test_sandbox_failure_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(raises=True)
        result = run_gate_b(
            _patch(_FIXING_DIFF), root=tmp_path, sandbox=sandbox, artifacts=_DictStore()
        )
        assert result is None

    def test_patch_that_does_not_apply_is_inconclusive(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(_exec_result(exit_code=0))
        result = run_gate_b(
            _patch(_MISMATCHED_DIFF), root=tmp_path, sandbox=sandbox, artifacts=_DictStore()
        )
        assert result is None
        assert sandbox.specs == []

    def test_nested_changed_file_is_bundled(self, tmp_path: Path) -> None:
        # A patch to a file in a subdirectory: the scratch tree then contains a
        # directory, exercising the bundle's file-vs-directory handling.
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        sandbox = _FakeSandbox(_exec_result(exit_code=0))
        result = run_gate_b(
            _patch(_NESTED_FIXING_DIFF, files_changed=("pkg/app.py",)),
            root=tmp_path,
            sandbox=sandbox,
            artifacts=_DictStore(),
        )
        assert result is True
