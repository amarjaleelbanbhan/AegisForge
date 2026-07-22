"""Gate A ("applies cleanly") and Gate C ("rescan clean") from the patch
validation pipeline (MPS §16) — the two of the four gates that don't need
sandboxed code execution (ADR-0004). Gate B ("existing tests pass") and
Gate D ("original PoC neutralized") need to run the analyzed project's own
code, which needs Phase 6's `SandboxPort` and doesn't exist yet; nothing
here attempts them.

`apply_and_rescan` copies only the files a `Patch` touches into a scratch
directory, applies the diff there via `git apply` (a trusted, widely
available tool — never the analyzed project's own code), and re-runs the
same scanners against the patched copy to check whether a finding with the
same `rule_id` still appears. Neither step executes anything from the
analyzed project.

The diff comes from an LLM (`RepairAgent`), which this module treats as
untrusted input per ADR-0004's spirit: `Patch.files_changed` entries are
validated to be plain relative paths with no `..` traversal or absolute
paths before anything is read from `root` or written to the scratch
directory, so a crafted diff can't read or write outside the sandbox this
function itself sets up.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
import tarfile
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from cortexward.agents.poc import ArtifactStore, run_poc_in_sandbox
from cortexward.domain import Evidence, EvidenceKind, Finding, Patch
from cortexward.ports import ExecutionSpec, SandboxPort, ScannerPort

_DRIVE_LETTER_PREFIX_LENGTH = 2
_GIT_APPLY_TIMEOUT_SECONDS = 30
"""Applying a small diff should be near-instant; bounded so a hung `git`
process can't hang gate verification indefinitely."""

# pytest's documented exit codes: 0 = all passed, 1 = tests failed, 5 = no
# tests were collected. Anything else (2/3/4, or a non-pytest failure) is an
# error we can't read as a clean pass/fail, so it's treated as inconclusive.
_PYTEST_ALL_PASSED = 0
_PYTEST_TESTS_FAILED = 1


def _is_safe_relative_path(path: str) -> bool:
    """True if `path` is a plain relative path: no `..` traversal, no POSIX
    root, no Windows drive letter. Pure string logic, deliberately not
    `pathlib`'s `is_absolute()` — that check is OS-dependent (a Windows
    drive-letter path like `C:/evil.py` isn't "absolute" under POSIX
    semantics), and this must reject it the same way on every platform
    regardless of which OS the check happens to run on.
    """
    normalized = path.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return False
    if len(normalized) >= _DRIVE_LETTER_PREFIX_LENGTH and normalized[1] == ":":
        return False
    return ".." not in normalized.split("/")


def _git_apply(diff_path: Path, *, cwd: Path) -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    try:
        # Full resolved path from shutil.which (not a partial "git"), no
        # shell; deliberately omits --unsafe-paths so git's own default
        # path-traversal protections stay in effect.
        process = subprocess.run(  # noqa: S603 # nosec B603
            [git, "apply", str(diff_path)],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_APPLY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # Same "inconclusive" treatment as git being unavailable at all --
        # apply_and_rescan returns None, never guesses at a gate outcome.
        return False
    return process.returncode == 0


@contextmanager
def _patched_scratch(patch: Patch, root: Path) -> Iterator[Path | None]:
    """Yield a scratch dir holding `patch`'s changed files with the diff applied,
    or `None` if that couldn't be done (no/unsafe `files_changed`, a missing
    source file, `git` unavailable, or the diff didn't apply).

    Shared by every gate that needs the patched code on disk (rescan, Gate D),
    so the untrusted-diff handling (path-traversal validation, `git apply`
    without `--unsafe-paths`) lives in exactly one place (ADR-0004).
    """
    if not patch.files_changed or not all(
        _is_safe_relative_path(relative) for relative in patch.files_changed
    ):
        yield None
        return
    with tempfile.TemporaryDirectory() as scratch:
        scratch_root = Path(scratch)
        for relative in patch.files_changed:
            source = root / relative
            if not source.is_file():
                yield None
                return
            destination = scratch_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        diff_path = scratch_root / ".cortexward-patch.diff"
        diff_path.write_text(patch.diff, encoding="utf-8")
        if not _git_apply(diff_path, cwd=scratch_root):
            yield None
            return
        yield scratch_root


def apply_and_rescan(
    patch: Patch,
    finding: Finding,
    *,
    root: Path,
    scanners: Sequence[ScannerPort],
    languages: Sequence[str] = (),
) -> bool | None:
    """Applies `patch` to a scratch copy of the files it touches and re-scans
    (MPS §16 Gate C, "rescan clean").

    Returns `True` if the patch applied cleanly and a rescan no longer
    reports `finding.rule_id`, `False` if it applied cleanly but the rescan
    still reports it, or `None` if this couldn't be determined at all (no
    `files_changed`, an unsafe path, a missing source file, `git` not
    available, or the diff simply didn't apply) — `None` is "inconclusive,"
    never treated as either gate outcome.
    """
    with _patched_scratch(patch, root) as scratch_root:
        if scratch_root is None:
            return None
        rescanned = [
            raw for scanner in scanners for raw in scanner.scan(scratch_root, languages=languages)
        ]
        return not any(raw.rule_id == finding.rule_id for raw in rescanned)


def _poc_evidence(finding: Finding) -> Evidence | None:
    """The finding's supporting `EXPLOIT_POC` evidence with a stored PoC, if any."""
    for evidence in finding.evidence:
        if (
            evidence.kind is EvidenceKind.EXPLOIT_POC
            and evidence.supports
            and evidence.artifact_ref is not None
        ):
            return evidence
    return None


def _recorded_poc(finding: Finding, artifacts: ArtifactStore) -> tuple[str, str, str] | None:
    """The `(poc_code, marker, poc_path)` `PocAgent` stashed, or `None` if absent."""
    evidence = _poc_evidence(finding)
    if evidence is None or evidence.artifact_ref is None:
        return None
    marker = evidence.data.get("poc_marker")
    poc_path = evidence.data.get("poc_path")
    if not marker or not poc_path or not _is_safe_relative_path(poc_path):
        return None
    try:
        poc_code = artifacts.get_artifact(evidence.artifact_ref).decode("utf-8")
    except KeyError:
        return None
    return poc_code, marker, poc_path


def poc_neutralized(
    patch: Patch,
    finding: Finding,
    *,
    root: Path,
    sandbox: SandboxPort,
    artifacts: ArtifactStore,
) -> bool | None:
    """Re-runs the finding's own recorded PoC against the patched code (MPS §16
    Gate D, "original PoC neutralized").

    Reuses the *exact* PoC `PocAgent` already proved triggers on the vulnerable
    code (fetched from the store via the `EXPLOIT_POC` evidence's `artifact_ref`)
    and the same unique marker — so this genuinely checks the exploit is
    neutralized, not merely that some command exited zero. Returns `True` if
    that same PoC no longer triggers against the patched file, `False` if it
    still does, or `None` if inconclusive (no recorded PoC, the patch didn't
    apply, the PoC couldn't run). A non-trigger is only meaningful *because*
    the identical PoC demonstrably triggered before the patch.
    """
    recorded = _recorded_poc(finding, artifacts)
    if recorded is None:
        return None
    poc_code, marker, poc_path = recorded
    with _patched_scratch(patch, root) as scratch_root:
        if scratch_root is None:
            return None
        patched_source = _read_patched_target(scratch_root, root, poc_path)
        if patched_source is None:
            return None
        triggered = run_poc_in_sandbox(
            relative=poc_path,
            source=patched_source,
            poc_code=poc_code,
            marker=marker,
            sandbox=sandbox,
            artifacts=artifacts,
        )
    return None if triggered is None else not triggered


def _read_patched_target(scratch_root: Path, root: Path, poc_path: str) -> str | None:
    """The PoC's target file after patching: the scratch copy if the patch
    touched it, else the original (a patch that doesn't touch the vulnerable
    file simply doesn't neutralize the exploit — not an error)."""
    patched = scratch_root / poc_path
    if patched.is_file():
        return patched.read_text(encoding="utf-8", errors="replace")
    original = root / poc_path
    if original.is_file():
        return original.read_text(encoding="utf-8", errors="replace")
    return None


def tests_pass_in_sandbox(
    patch: Patch,
    *,
    root: Path,
    sandbox: SandboxPort,
    artifacts: ArtifactStore,
) -> bool | None:
    """Runs the patched project's own test suite in the sandbox (MPS §16 Gate B,
    "existing tests pass").

    Applies `patch`, bundles the changed files, and runs `python -m pytest`
    inside the isolated sandbox. Returns `True` only when pytest reports every
    test passed (exit 0), `False` when a test failed (exit 1), or `None` when
    inconclusive — no tests collected (exit 5), pytest not installed in the
    sandbox image, the patch didn't apply, or any infrastructure failure.

    Deliberately never a false pass: an inconclusive run (including the common
    "the base image has no pytest / the target's deps aren't installed" case —
    per-target images are future work, see `ExecutionSpec.image`) leaves the
    gate unset rather than claiming success.
    """
    with _patched_scratch(patch, root) as scratch_root:
        if scratch_root is None:
            return None
        bundle = _tar_directory(scratch_root)
        ref = artifacts.put_artifact(bundle)
        try:
            outcome = sandbox.execute(
                ExecutionSpec(command=("python", "-m", "pytest", "-q"), input_bundle_ref=ref)
            )
        except Exception:  # any sandbox infra failure is inconclusive, not a crash
            return None
    if outcome.timed_out:
        return None
    if outcome.exit_code == _PYTEST_ALL_PASSED:
        return True
    if outcome.exit_code == _PYTEST_TESTS_FAILED:
        return False
    return None


def _tar_directory(directory: Path) -> bytes:
    """A tar of every file under `directory` (the sandbox unpacks it into /workspace)."""
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(directory).as_posix())
    return buffer.getvalue()


__all__ = [
    "apply_and_rescan",
    "poc_neutralized",
    "tests_pass_in_sandbox",
]
