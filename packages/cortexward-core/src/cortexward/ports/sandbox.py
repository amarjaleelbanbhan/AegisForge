"""Sandbox port: isolated dynamic execution (MPS §22.4, ADR-0004).

Realizes Verification Ladder rungs 3-4 (dynamic PoC, differential test).
Every execution runs under an explicit, deny-by-default policy: no network
egress unless allow-listed, no host mounts, resource-capped, ephemeral. The
result is returned as inert data — stdout/stderr/exit code/artifacts — never
as something that can itself trigger further action.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from cortexward.ports._base import PortModel


class EgressPolicy(StrEnum):
    DENY_ALL = "deny_all"
    """No network access. The default and the safest option."""
    ALLOW_LIST = "allow_list"
    """Network access only to explicitly declared hosts, and logged."""


class ResourceLimits(PortModel):
    cpu_seconds: float = 30.0
    memory_mb: int = 512
    wall_clock_seconds: float = 90.0
    """Hard cap on total execution time (MPS §24 performance target)."""


class ExecutionSpec(PortModel):
    """A request to run one command inside an isolated sandbox."""

    command: tuple[str, ...]
    input_bundle_ref: str
    """Content-addressed reference to the (read-only) input filesystem bundle."""
    image: str = "python:3.11-slim"
    """The container image ``command`` runs inside.

    Defaults to this project's own primary supported runtime (MPS §6.1:
    "Python first") — a target's own language/dependency needs mean this is
    genuinely target-specific in general, but no port field existed to say
    so before now, and Python is the one language this project can
    currently give a defensible default for. Per-target image selection
    (installing a target's own declared dependencies into a purpose-built
    image before executing its tests/PoC) is future work once multi-
    language dynamic execution is in scope.
    """
    env: dict[str, str] = Field(default_factory=dict)
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    egress: EgressPolicy = EgressPolicy.DENY_ALL
    allowed_hosts: tuple[str, ...] = ()
    """Only consulted when ``egress`` is :attr:`EgressPolicy.ALLOW_LIST`."""


class ExecutionResult(PortModel):
    """The outcome of one sandboxed execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float
    artifact_refs: tuple[str, ...] = ()
    """Content-addressed references to files produced during execution."""


@runtime_checkable
class SandboxPort(Protocol):
    """An isolated execution backend (container, gVisor, or microVM tier)."""

    @property
    def isolation_tier(self) -> str:
        """Identifies the isolation strength, e.g. ``"docker-seccomp"``."""
        ...

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        """Run ``spec`` to completion (or until its limits are hit) and return
        the result. MUST enforce ``spec.limits`` and ``spec.egress``."""
        ...
