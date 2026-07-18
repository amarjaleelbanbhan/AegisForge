# cortexward-storage

`StoragePort` adapters (MPS §17.1/§19, ADR-0008): the append-only, event-sourced finding log plus
content-addressed artifact storage, so orchestration code never imports a database driver directly.

## What exists

- **`SqliteStoragePort`** — a local SQLite-backed `StoragePort`. Findings are never stored
  directly; only the append-only `FindingEvent` log is persisted, and `get_finding`/`list_findings`
  derive the current state by replaying it through `cortexward.ports.materialize_finding` on every
  read — exactly the "materialized read model" ADR-0008 specifies. Registered under the
  `cortexward.storage` entry-point group as `sqlite`.

```python
from cortexward.storage import SqliteStoragePort

with SqliteStoragePort("findings.db") as storage:
    storage.append_event(detected_event)
    storage.append_event(evidence_attached_event)
    finding = storage.get_finding(detected_event.finding_id)  # replayed from the log
```

- **`materialize_finding`** (`cortexward-core`, `cortexward.ports`) — the pure event-replay logic
  shared by every `StoragePort` adapter, not duplicated here. `FindingEvent.finding` (new this
  session) carries the full detected `Finding` snapshot on `DETECTED` events; every later event
  layers a delta onto it (`with_evidence`, `apply_assessment`, `PATCHED` on a fully-validated
  `Patch`, `DISMISSED` on suppression).

## Design notes

- `list_findings(run_id)` has no dedicated `run_id` column: `Finding.provenance.run_id` (already
  part of the domain model, MPS §10) is what a finding's own detected-run identity is read from,
  rather than inventing a second, redundant field.
- Content-addressing for `put_artifact`/`get_artifact` is `sha256:<hex digest>`; `get_artifact`
  raises `KeyError` on an unknown reference, matching `StoragePort`'s own conformance test fake.
- Uses stdlib `sqlite3` only, mirroring `SqliteRepositoryMemory` (`cortexward-agents`); not safe to
  share across threads.

## Deliberately not implemented

- **Postgres + pgvector** (MPS §19's server/scale reference adapter) — `StoragePort`'s protocol
  supports it, but building it needs a running Postgres instance to verify against (this
  environment has none), the same "needs unavailable runtime infrastructure" gap `SandboxPort`'s
  Docker/gVisor adapter has.
