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
import tempfile
from collections.abc import Sequence
from pathlib import Path

from cortexward.domain import Finding, Patch
from cortexward.ports import ScannerPort

_DRIVE_LETTER_PREFIX_LENGTH = 2


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
    # Full resolved path from shutil.which (not a partial "git"), no shell;
    # deliberately omits --unsafe-paths so git's own default path-traversal
    # protections stay in effect.
    process = subprocess.run(  # noqa: S603 # nosec B603
        [git, "apply", str(diff_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return process.returncode == 0


def apply_and_rescan(
    patch: Patch,
    finding: Finding,
    *,
    root: Path,
    scanners: Sequence[ScannerPort],
    languages: Sequence[str] = (),
) -> bool | None:
    """Applies `patch` to a scratch copy of the files it touches and re-scans.

    Returns `True` if the patch applied cleanly and a rescan no longer
    reports `finding.rule_id`, `False` if it applied cleanly but the rescan
    still reports it, or `None` if this couldn't be determined at all (no
    `files_changed`, an unsafe path, a missing source file, `git` not
    available, or the diff simply didn't apply) — `None` is "inconclusive,"
    never treated as either gate outcome.
    """
    if not patch.files_changed:
        return None
    if not all(_is_safe_relative_path(relative) for relative in patch.files_changed):
        return None

    with tempfile.TemporaryDirectory() as scratch:
        scratch_root = Path(scratch)
        for relative in patch.files_changed:
            source = root / relative
            if not source.is_file():
                return None
            destination = scratch_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())

        diff_path = scratch_root / ".cortexward-patch.diff"
        diff_path.write_text(patch.diff, encoding="utf-8")
        if not _git_apply(diff_path, cwd=scratch_root):
            return None

        rescanned = [
            raw for scanner in scanners for raw in scanner.scan(scratch_root, languages=languages)
        ]
        return not any(raw.rule_id == finding.rule_id for raw in rescanned)


__all__ = ["apply_and_rescan"]
