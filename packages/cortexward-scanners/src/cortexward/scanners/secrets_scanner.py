"""A :class:`~cortexward.ports.ScannerPort` adapter wrapping detect-secrets.

Uses detect-secrets' Python API directly (`SecretsCollection.scan_files`) —
it's a pure-Python library with no external binary, unlike Bandit. File
discovery is done here (not via detect-secrets' own `get_files_to_scan`)
because that helper resolves reported paths relative to the *process's*
current working directory unless a matching ``root`` kwarg is threaded
through just right; walking the tree ourselves and passing absolute paths
straight into `scan_files` sidesteps that entirely and matches the same
root-relative-path convention every other scanner adapter here uses.
`SecretsCollection` itself is constructed with `root=str(resolved_root)`
for the same reason: left at its default, it computes each secret's
reported path via `os.path.relpath(..., os.getcwd())`, which raises on
Windows whenever the scanned root and the process's cwd sit on different
drives — a real scenario (`ward scan` invoked against a project on a
different drive than the shell's cwd), not just a test artifact.

**Security property preserved:** detect-secrets never returns a matched
secret's actual value, only a one-way hash (`hashed_secret`) — `RawFinding
.raw` carries that hash forward, never the plaintext, so a scan report
itself can never become a new leak.

Secrets aren't language-specific (a hardcoded credential in a `.env` or
`.yml` file is exactly as real a leak as one in a `.py` file), so unlike
Bandit this scanner ignores the `languages` filter entirely — see
`SecretsScanner`'s docstring.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from detect_secrets import SecretsCollection  # type: ignore[attr-defined]
from detect_secrets.settings import default_settings

from cortexward.domain import SourceLocation
from cortexward.ports import RawFinding

_EXCLUDED_DIR_NAMES = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".hypothesis",
)

_HARDCODED_CREDENTIALS_CWE = 798
"""CWE-798: Use of Hard-coded Credentials — the one CWE every secret-type
detect-secrets plugin reports, since the tool has no finer-grained mapping
of its own."""


def _iter_scannable_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIR_NAMES or part.endswith(".egg-info") for part in path.parts):
            continue
        files.append(path)
    return files


def _int(value: object, *, default: int) -> int:
    """`value` as an `int` if it genuinely is one, else `default`.

    detect-secrets' `.json()` shape isn't a versioned contract this codebase
    controls; treating it as untrusted (ADR-0004) means never letting a
    surprising type crash the whole scan.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _finding_from_secret(secret: Mapping[str, object], *, root: Path) -> RawFinding:
    filename = Path(str(secret["filename"]))
    try:
        relative = filename.relative_to(root)
    except ValueError:
        relative = filename
    secret_type = str(secret.get("type", "secret"))
    return RawFinding(
        rule_id=secret_type,
        message=f"Potential secret detected: {secret_type}",
        location=SourceLocation(
            path=str(relative), start_line=_int(secret.get("line_number"), default=1)
        ),
        severity_hint="CRITICAL",
        cwe=_HARDCODED_CREDENTIALS_CWE,
        raw={
            "hashed_secret": str(secret.get("hashed_secret", "")),
            "is_verified": str(secret.get("is_verified", False)),
        },
    )


class SecretsScanner:
    """Runs detect-secrets over a project and yields findings as `RawFinding`.

    The `languages` filter is accepted for `ScannerPort` conformance but
    intentionally ignored: secrets are not scoped to a single language
    grammar the way SAST rules are, so this scanner always scans every
    non-excluded file regardless of what languages are requested.
    """

    name = "detect-secrets"

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        del languages
        resolved_root = root.resolve()
        files = _iter_scannable_files(resolved_root)
        if not files:
            return
        secrets = SecretsCollection(root=str(resolved_root))
        with default_settings():
            secrets.scan_files(*(str(f) for f in files))
        for secret_set in secrets.data.values():
            for secret in secret_set:
                yield _finding_from_secret(secret.json(), root=resolved_root)
