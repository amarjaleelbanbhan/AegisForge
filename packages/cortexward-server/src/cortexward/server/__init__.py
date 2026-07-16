"""CortexWard's REST API (MPS §20.2, Phase 8).

Deliberately does *not* re-export `app` here (`from cortexward.server.app
import app` would create a genuine footgun: `import cortexward.server.app
as x` binds `x` to whatever attribute `cortexward.server.app` resolves to
on the *package* object, and a re-export here would rebind that attribute
from "the `app` submodule" to "the FastAPI instance," so `x` would
silently become the FastAPI app instead of the module -- verified this
would actually happen, not just a theoretical concern). Import the app
directly from its submodule: `from cortexward.server.app import app`, or
run it with `uvicorn cortexward.server.app:app` (both unaffected by this,
since neither goes through this file's exports).
"""

from __future__ import annotations

from cortexward.server.jobs import Job, JobStatus, JobStore

__all__ = ["Job", "JobStatus", "JobStore"]
