# cortexward-server

CortexWard's REST API (MPS §20.2, Phase 8) — a v1 slice of the full contract.

```
POST /v1/scans                  # create a scan job, 202 Accepted
GET  /v1/scans/{id}              # poll job status
GET  /v1/scans/{id}/findings     # list findings once the job has completed
```

`POST /v1/scans` mirrors `ward scan`'s CLI flags:

```json
{
  "root": "/path/to/project",
  "languages": ["python"],
  "llm_provider": "ollama",
  "llm_model": "qwen2.5-coder:7b",
  "reachability": true
}
```

Omit `llm_provider` for a plain scan-and-correlate run (no LLM verification) — matching `ward
scan` with no `--llm-*` flags. Reuses `cortexward.orchestrator.build_pipeline()`, the same
`SequentialOrchestrator`-or-`AgentOrchestrator` decision the CLI makes, so a scan behaves
identically from either surface.

Run it with `uvicorn cortexward.server.app:app` (install the `serve` extra for `uvicorn`:
`uv pip install "cortexward-server[serve]"`).

**Not yet implemented, deliberately** (see `app.py`'s module docstring for the full reasoning):
authentication, rate-limiting, per-finding `verify`/`fix` endpoints, `GET /v1/runs/{id}/manifest`,
and `POST /v1/webhooks/{provider}` — each needs infrastructure (a persisted finding store, a
`VCSPort` adapter, ...) this project doesn't have yet. Job state is in-memory and single-process
only. This is a single-tenant, trusted-caller tool today, not something to expose on an untrusted
network without adding real authentication and path scoping first.
