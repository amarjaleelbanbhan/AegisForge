"""In-memory scan-job tracking for the REST API (MPS §20.2).

A deliberately minimal, single-process job store: a run's status and
result live in a plain dict, keyed by job id, for the lifetime of the
server process. There is no persistence (a restart loses all job history)
and no cross-process sharing (this store cannot back more than one server
worker) — both are genuine limitations of this v1, not overlooked:
`StoragePort` (MPS §17.1) has no concrete adapter yet, so nothing durable
exists to persist jobs into. Fine for the self-hostable, single-process,
laptop-scale deployment this project targets today; a multi-worker
deployment needs a real `StoragePort` adapter behind this same interface
first.

`Job` stays a frozen value, matching the functional-update style used
throughout the domain core and agent framework (`Finding.with_state`,
`RunState.with_*`) — `JobStore` is the one place holding genuinely mutable
state (a dict behind a lock), exactly the way a database would be, rather
than every consumer of a `Job` needing to reason about it changing under
them.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import uuid4

from cortexward.ports import RunResult


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Job:
    id: str
    status: JobStatus = JobStatus.QUEUED
    result: RunResult | None = None
    error: str | None = None


class JobStore:
    """Thread-safe in-memory job tracking: one process, no persistence."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=f"job_{uuid4().hex[:16]}")
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._jobs[job_id] = replace(job, status=JobStatus.RUNNING)

    def mark_completed(self, job_id: str, result: RunResult) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._jobs[job_id] = replace(job, status=JobStatus.COMPLETED, result=result)

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._jobs[job_id] = replace(job, status=JobStatus.FAILED, error=error)


__all__ = ["Job", "JobStatus", "JobStore"]
