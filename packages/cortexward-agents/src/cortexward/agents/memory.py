"""Memory abstractions (MPS §15): repository memory and global knowledge.

Three tiers per MPS §15:

1. **Run memory** — ephemeral `RunState` (`cortexward.agents.state`), not
   duplicated here.
2. **Repository memory** — persisted triage decisions, suppressions,
   accepted-patch patterns, fingerprint history *for a given repository*.
3. **Global knowledge** — CWE/CVE references, source/sink catalogs, curated
   exemplars, shared across every repository/run.

`RepositoryMemory` and `GlobalKnowledge` are `Protocol`s so a real
deployment can back them with a persistent store without any *caller*
depending on a database driver; `InMemoryRepositoryMemory` is what every
agent/test in this package exercises against by default,
`SqliteRepositoryMemory` is the persistent reference implementation
(stdlib `sqlite3` only — `RepositoryMemory`'s protocol is small and
self-contained enough not to need the broader, still-undesigned
`StoragePort` event-sourcing machinery just to persist a suppression list).

Memory only *informs* prompts via retrieval — it never updates model
weights and never bypasses the Verification Ladder (MPS §15).

`fingerprint_for` lives in `cortexward.domain` (re-exported here for
backward compatibility) — it turned out to be a domain-level identity
concept, not agent-specific: the CLI's `--baseline` suppression file needs
the exact same fingerprint this module's `RepositoryMemory` uses, without
needing to depend on the whole agent framework to compute one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
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

    `SqliteRepositoryMemory` below persists across restarts; this one is
    what lets a single orchestrated run (and most tests in this package)
    use repository memory without a database.
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


class SqliteRepositoryMemory:
    """A `RepositoryMemory` persisted to a local SQLite database.

    `StoragePort` (MPS §17.1, ADR-0008) is the general event-sourced
    finding log; its `FindingEvent` model has no field for a finding's own
    core data (rule_id, locations, ...), so a real adapter for it needs a
    port-level design decision this project hasn't made yet. Repository
    memory has no such gap — `RepositoryMemory`'s three-method protocol is
    fully self-contained — so this closes the "lost when the process
    exits" limitation `InMemoryRepositoryMemory` documents, without
    needing to wait on that broader decision.

    Uses stdlib `sqlite3` only; no new dependency. Not safe to share across
    threads (matching `InMemoryRepositoryMemory`'s own single-threaded
    assumption — sqlite3 connections aren't thread-safe by default either).
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database))
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS suppressions ("
            "fingerprint TEXT PRIMARY KEY, reason TEXT NOT NULL)"
        )
        self._connection.commit()

    def record_suppression(self, fingerprint: str, reason: str) -> None:
        self._connection.execute(
            "INSERT INTO suppressions (fingerprint, reason) VALUES (?, ?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET reason = excluded.reason",
            (fingerprint, reason),
        )
        self._connection.commit()

    def is_suppressed(self, fingerprint: str) -> bool:
        cursor = self._connection.execute(
            "SELECT 1 FROM suppressions WHERE fingerprint = ?", (fingerprint,)
        )
        return cursor.fetchone() is not None

    def suppressions(self) -> tuple[SuppressionRecord, ...]:
        cursor = self._connection.execute(
            "SELECT fingerprint, reason FROM suppressions ORDER BY fingerprint"
        )
        return tuple(
            SuppressionRecord(fingerprint=row[0], reason=row[1]) for row in cursor.fetchall()
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqliteRepositoryMemory:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


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
    "SqliteRepositoryMemory",
    "StaticGlobalKnowledge",
    "SuppressionRecord",
    "fingerprint_for",
]
