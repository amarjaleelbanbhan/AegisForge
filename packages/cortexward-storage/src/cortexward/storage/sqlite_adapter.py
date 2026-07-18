"""SQLite reference adapter for `StoragePort` (MPS §17.1/§19, ADR-0008).

`FindingEvent` gained a `finding` field (this session, alongside
`cortexward.ports.materialize_finding`) carrying the full detected `Finding`
snapshot on `DETECTED` events — the one piece of information the port was
previously missing to ever reconstruct a finding's materialized state from
its own event log. This adapter is what that fix was for: it stores nothing
but the append-only event log itself, and derives every read (`get_finding`,
`list_findings`) by replaying it through `materialize_finding`, exactly as
ADR-0008 specifies ("current state as a materialized read model").

`list_findings(run_id)` has no explicit `run_id` column to key off, since
neither `FindingEvent` nor `Finding` were ever given one -- but
`Finding.provenance.run_id` already exists for precisely this purpose
(`Provenance` MPS §10: "where a piece of data came from"), so a finding's own
detected-run identity is read from there rather than inventing a second,
redundant field.

Uses stdlib `sqlite3` only, mirroring `SqliteRepositoryMemory`
(`cortexward-agents`); not safe to share across threads, matching that
adapter's own single-threaded assumption.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from cortexward.domain import Finding
from cortexward.ports import FindingEvent, materialize_finding


class SqliteStoragePort:
    """A `StoragePort` persisted to a local SQLite database."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database))
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "finding_id TEXT NOT NULL, "
            "payload TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_finding_id ON events(finding_id)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS artifacts (ref TEXT PRIMARY KEY, content BLOB NOT NULL)"
        )
        self._connection.commit()

    def append_event(self, event: FindingEvent) -> None:
        """Durably record `event`. Never mutates or removes prior events."""
        self._connection.execute(
            "INSERT INTO events (finding_id, payload) VALUES (?, ?)",
            (event.finding_id, event.model_dump_json()),
        )
        self._connection.commit()

    def events_for(self, finding_id: str) -> Iterable[FindingEvent]:
        """Return all events for `finding_id`, in the order they were appended.

        Append order (the `seq` autoincrement column) is used rather than
        the caller-supplied `occurred_at`, since two events can legitimately
        share a timestamp (clock resolution) but can never share an append
        order -- and `materialize_finding` replays strictly in the order
        it's given.
        """
        cursor = self._connection.execute(
            "SELECT payload FROM events WHERE finding_id = ? ORDER BY seq ASC",
            (finding_id,),
        )
        return tuple(FindingEvent.model_validate_json(row[0]) for row in cursor.fetchall())

    def get_finding(self, finding_id: str) -> Finding | None:
        """Return the current materialized state of a finding, if known."""
        return materialize_finding(self.events_for(finding_id))

    def list_findings(self, run_id: str) -> Iterable[Finding]:
        """Return the current materialized findings detected during `run_id`."""
        cursor = self._connection.execute("SELECT DISTINCT finding_id FROM events")
        findings: list[Finding] = []
        for (finding_id,) in cursor.fetchall():
            finding = self.get_finding(finding_id)
            if finding is not None and finding.provenance.run_id == run_id:
                findings.append(finding)
        return tuple(findings)

    def put_artifact(self, content: bytes) -> str:
        """Store `content` and return its content-addressed reference."""
        ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
        self._connection.execute(
            "INSERT OR IGNORE INTO artifacts (ref, content) VALUES (?, ?)", (ref, content)
        )
        self._connection.commit()
        return ref

    def get_artifact(self, ref: str) -> bytes:
        """Retrieve previously stored content by its reference.

        Raises `KeyError` on an unknown reference, matching this port's own
        conformance test's reference `_InMemoryStorage` fake.
        """
        cursor = self._connection.execute("SELECT content FROM artifacts WHERE ref = ?", (ref,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(ref)
        content = row[0]
        return bytes(content)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqliteStoragePort:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


__all__ = ["SqliteStoragePort"]
