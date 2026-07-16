"""Unit tests for `JobStore`."""

from __future__ import annotations

import pytest

from cortexward.ports import RunResult
from cortexward.server.jobs import JobStatus, JobStore

pytestmark = pytest.mark.unit


def _result(run_id: str = "run_1") -> RunResult:
    return RunResult(run_id=run_id, findings=())


class TestJobStore:
    def test_create_returns_a_queued_job_with_a_generated_id(self) -> None:
        store = JobStore()
        job = store.create()
        assert job.id.startswith("job_")
        assert job.status == JobStatus.QUEUED
        assert job.result is None
        assert job.error is None

    def test_two_created_jobs_get_different_ids(self) -> None:
        store = JobStore()
        assert store.create().id != store.create().id

    def test_get_returns_the_created_job(self) -> None:
        store = JobStore()
        job = store.create()
        assert store.get(job.id) is not None
        assert store.get(job.id).id == job.id  # type: ignore[union-attr]

    def test_get_unknown_id_returns_none(self) -> None:
        store = JobStore()
        assert store.get("job_does_not_exist") is None

    def test_mark_running_updates_status(self) -> None:
        store = JobStore()
        job = store.create()
        store.mark_running(job.id)
        assert store.get(job.id).status == JobStatus.RUNNING  # type: ignore[union-attr]

    def test_mark_completed_updates_status_and_result(self) -> None:
        store = JobStore()
        job = store.create()
        result = _result()
        store.mark_completed(job.id, result)
        updated = store.get(job.id)
        assert updated is not None
        assert updated.status == JobStatus.COMPLETED
        assert updated.result is result

    def test_mark_failed_updates_status_and_error(self) -> None:
        store = JobStore()
        job = store.create()
        store.mark_failed(job.id, "boom")
        updated = store.get(job.id)
        assert updated is not None
        assert updated.status == JobStatus.FAILED
        assert updated.error == "boom"

    def test_marking_an_unknown_job_is_a_no_op(self) -> None:
        store = JobStore()
        store.mark_running("job_does_not_exist")
        store.mark_completed("job_does_not_exist", _result())
        store.mark_failed("job_does_not_exist", "boom")
        assert store.get("job_does_not_exist") is None

    def test_the_original_job_object_is_unmodified_by_updates(self) -> None:
        store = JobStore()
        job = store.create()
        store.mark_running(job.id)
        assert job.status == JobStatus.QUEUED
