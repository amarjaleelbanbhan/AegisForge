"""CortexWard REST API (MPS §20.2, Phase 8).

A v1 slice of the MPS's full contract: `POST /v1/scans` (create a scan
job), `GET /v1/scans/{id}` (poll status), `GET /v1/scans/{id}/findings`
(list results once complete). Reuses
`cortexward.orchestrator.build_pipeline()` — the same "`SequentialOrchestrator`
or `AgentOrchestrator`?" decision `ward scan` makes — so a scan request
supports the identical LLM-provider options the CLI does, and a scan
request behaves identically whether it's driven from the CLI or here.

**Not yet implemented, deliberately**: authentication, rate-limiting,
per-finding `POST /v1/findings/{id}/verify`/`fix` (need a persisted,
independently-addressable finding store — `StoragePort` has no adapter
yet), `GET /v1/runs/{id}/manifest` (`RunManifest` isn't wired to live
scans, only to the offline benchmark harness), and
`POST /v1/webhooks/{provider}` (needs a `VCSPort` adapter, none exist
yet). Job state is in-memory and single-process only — a restart loses
all history, and this cannot back more than one server worker (see
`jobs.py`).

**Security note**: `POST /v1/scans` accepts an arbitrary filesystem `root`
path on the server with no access control or path restriction — this is a
single-tenant, trusted-caller tool today (matching `ward scan`'s own CLI
trust model), not something to expose on an untrusted network without
adding real authentication and path scoping first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from cortexward.llm import LLMProviderConfig, Provider
from cortexward.orchestrator import build_pipeline
from cortexward.ports import AnalysisRequest
from cortexward.server.jobs import Job, JobStore

app = FastAPI(
    title="CortexWard",
    description="An autonomous AI software security engineer — REST API (v1 slice, MPS §20.2).",
    version="0.1.0",
)
_jobs = JobStore()

_JobStatusLiteral = Literal["queued", "running", "completed", "failed"]


class ScanRequest(BaseModel):
    """Mirrors `ward scan`'s CLI flags: same options, same semantics."""

    root: str
    languages: tuple[str, ...] = ()
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_key_env: str | None = None
    llm_base_url: str | None = None
    reachability: bool = True


class ScanJobResponse(BaseModel):
    id: str
    status: _JobStatusLiteral
    error: str | None = None


class FindingsResponse(BaseModel):
    id: str
    status: _JobStatusLiteral
    findings: tuple[dict[str, object], ...] = ()


def _resolve_llm_config(request: ScanRequest) -> LLMProviderConfig | None:
    if request.llm_provider is None:
        return None
    try:
        provider = Provider(request.llm_provider)
    except ValueError as exc:
        valid = ", ".join(member.value for member in Provider)
        raise HTTPException(
            status_code=422,
            detail=f"invalid llm_provider {request.llm_provider!r}; expected one of: {valid}",
        ) from exc
    if request.llm_model is None:
        raise HTTPException(
            status_code=422, detail="llm_model is required when llm_provider is set"
        )
    return LLMProviderConfig(
        provider=provider,
        model=request.llm_model,
        api_key=request.llm_api_key,
        api_key_env=request.llm_api_key_env,
        base_url=request.llm_base_url,
    )


def _run_scan(
    job_id: str,
    *,
    llm_config: LLMProviderConfig | None,
    root: Path,
    languages: tuple[str, ...],
    reachability: bool,
) -> None:
    _jobs.mark_running(job_id)
    try:
        orchestrator = build_pipeline(
            llm_config=llm_config, root=root, languages=languages, reachability=reachability
        )
        result = orchestrator.run(AnalysisRequest(root=root, languages=languages))
    except Exception as exc:
        _jobs.mark_failed(job_id, str(exc))
        return
    _jobs.mark_completed(job_id, result)


def _get_job_or_404(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no scan job {job_id!r}")
    return job


@app.post("/v1/scans", status_code=202)
def create_scan(request: ScanRequest, background_tasks: BackgroundTasks) -> ScanJobResponse:
    llm_config = _resolve_llm_config(request)
    root = Path(request.root)
    if not root.is_dir():
        raise HTTPException(status_code=422, detail=f"root {request.root!r} is not a directory")

    job = _jobs.create()
    background_tasks.add_task(
        _run_scan,
        job.id,
        llm_config=llm_config,
        root=root.resolve(),
        languages=tuple(request.languages),
        reachability=request.reachability,
    )
    return ScanJobResponse(id=job.id, status=job.status.value)


@app.get("/v1/scans/{scan_id}")
def get_scan(scan_id: str) -> ScanJobResponse:
    job = _get_job_or_404(scan_id)
    return ScanJobResponse(id=job.id, status=job.status.value, error=job.error)


@app.get("/v1/scans/{scan_id}/findings")
def get_scan_findings(scan_id: str) -> FindingsResponse:
    job = _get_job_or_404(scan_id)
    findings = (
        tuple(finding.model_dump(mode="json") for finding in job.result.findings)
        if job.result is not None
        else ()
    )
    return FindingsResponse(id=job.id, status=job.status.value, findings=findings)


__all__ = ["app"]
