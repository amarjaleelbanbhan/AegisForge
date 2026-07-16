"""Memory abstractions (MPS §15): repository memory and global knowledge.

Three tiers per MPS §15:

1. **Run memory** — ephemeral `RunState` (`cortexward.agents.state`), not
   duplicated here.
2. **Repository memory** — persisted triage decisions, suppressions,
   accepted-patch patterns, fingerprint history *for a given repository*.
3. **Global knowledge** — CWE/CVE references, source/sink catalogs, curated
   exemplars, shared across every repository/run.

`RepositoryMemory` and `GlobalKnowledge` are `Protocol`s so a real
deployment can back them with `StoragePort` (SQLite/Postgres) without this
package depending on a database driver; the in-memory reference
implementations here are what every agent/test in this package exercises
against by default.

Memory only *informs* prompts via retrieval — it never updates model
weights and never bypasses the Verification Ladder (MPS §15).

`fingerprint_for` lives in `cortexward.domain` (re-exported here for
backward compatibility) — it turned out to be a domain-level identity
concept, not agent-specific: the CLI's `--baseline` suppression file needs
the exact same fingerprint this module's `RepositoryMemory` uses, without
needing to depend on the whole agent framework to compute one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cortexward.domain import fingerprint_for


@dataclass(frozen=True)
class SuppressionRecord:
    """One finding a human (or the Reviewer agent) decided not to act on."""

    fingerprint: str
    reason: str


@runtime_checkable
class RepositoryMemory(Protocol):
    """Persisted, repository-scoped triage history (MPS §15 tier 2)."""

    def record_suppression(self, fingerprint: str, reason: str) -> None: ...

    def is_suppressed(self, fingerprint: str) -> bool: ...

    def suppressions(self) -> tuple[SuppressionRecord, ...]: ...


class InMemoryRepositoryMemory:
    """A process-local reference `RepositoryMemory` — lost when the process exits.

    A real deployment persists this via `StoragePort` instead; this is what
    lets a single orchestrated run (and every test in this package) use
    repository memory without a database.
    """

    def __init__(self) -> None:
        self._suppressions: dict[str, str] = {}

    def record_suppression(self, fingerprint: str, reason: str) -> None:
        self._suppressions[fingerprint] = reason

    def is_suppressed(self, fingerprint: str) -> bool:
        return fingerprint in self._suppressions

    def suppressions(self) -> tuple[SuppressionRecord, ...]:
        return tuple(
            SuppressionRecord(fingerprint=fp, reason=reason)
            for fp, reason in self._suppressions.items()
        )


@runtime_checkable
class GlobalKnowledge(Protocol):
    """Shared, cross-repository reference material (MPS §15 tier 3)."""

    def cwe_summary(self, cwe: int) -> str | None: ...


_CWE_SUMMARIES: dict[int, str] = {
    22: "CWE-22 Path Traversal: unsanitized input reaches a filesystem path.",
    78: "CWE-78 OS Command Injection: unsanitized input reaches a shell command.",
    79: "CWE-79 Cross-Site Scripting: unsanitized input reaches an HTML response.",
    89: "CWE-89 SQL Injection: unsanitized input reaches a SQL query.",
    502: "CWE-502 Deserialization of Untrusted Data: untrusted input is deserialized unsafely.",
    798: "CWE-798 Use of Hard-coded Credentials: a secret is embedded in source or config.",
}


class StaticGlobalKnowledge:
    """A small, built-in reference `GlobalKnowledge` covering common CWEs.

    A real deployment would back this with a maintained CWE/CVE database;
    this reference implementation is deliberately minimal — enough to
    ground a Verifier/Reviewer prompt with one factual sentence about the
    weakness class, not a full curated-exemplar corpus (out of scope here).
    """

    def cwe_summary(self, cwe: int) -> str | None:
        return _CWE_SUMMARIES.get(cwe)


__all__ = [
    "GlobalKnowledge",
    "InMemoryRepositoryMemory",
    "RepositoryMemory",
    "StaticGlobalKnowledge",
    "SuppressionRecord",
    "fingerprint_for",
]
