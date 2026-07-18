"""Docker-backed `SandboxPort` implementation (MPS §22.4, ADR-0004).

`SandboxPort.execute(spec)`'s normative contract (MPS §22.4) is followed as
literally as a plain `docker` CLI invocation allows:

- **no network egress by default** — every container runs with
  ``--network none``. ``EgressPolicy.ALLOW_LIST`` is deliberately not
  supported: genuinely restricting egress to specific hosts needs a custom
  Docker network plus firewall/DNS rules this adapter doesn't build, and
  silently granting broader access than requested (or silently downgrading
  to deny-all) would both violate the policy the caller actually asked for
  — raising :class:`NotImplementedError` is the honest alternative to
  either.
- **read-only root** — ``--read-only``, with a ``--tmpfs /tmp`` scratch
  area (a container that can write nowhere at all can't do much).
- **ephemeral, per-run filesystem scrubbed afterward** — every container
  gets a fresh, uniquely-named instance, removed (``docker rm -f``) in a
  ``finally`` block regardless of outcome.
- **CPU/mem/time caps** — ``--memory``/``--memory-swap`` from
  :attr:`~cortexward.ports.ResourceLimits.memory_mb` directly;
  :attr:`~cortexward.ports.ResourceLimits.wall_clock_seconds` is enforced
  as a hard `subprocess` timeout (with an explicit ``docker kill`` on
  expiry, since killing the local ``docker`` CLI process does not by
  itself stop the container running server-side); ``cpu_seconds`` has no
  direct Docker equivalent (Docker's ``--cpus`` is a consumption *rate*,
  not a total-time budget) — see :func:`_cpu_limit` for the documented
  approximation used instead.
- **no host mounts** — nothing here ever passes ``-v <host path>:...``.
  The input bundle is streamed into the container with ``docker cp -``
  (a tar stream over the daemon API, not a shared filesystem mount), and
  any produced artifacts are retrieved the same way, before the
  container is ever started.
- **unprivileged user, `no-new-privileges`** — ``--user 1000:1000``,
  ``--security-opt no-new-privileges``, ``--cap-drop ALL``.
- **seccomp/AppArmor baseline** — Docker applies its own default
  seccomp/AppArmor profiles automatically unless a container explicitly
  disables them; this adapter never does, so the baseline applies without
  needing a custom profile of its own.
- **gVisor/Firecracker tier** — deliberately not implemented: it needs the
  ``runsc``/Firecracker runtime installed and configured on the host,
  unavailable infrastructure in any environment this project has verified
  against, exactly the same "needs infrastructure this environment
  doesn't have" gap the adapter as a whole has (see the package README).

Results (exit code, stdout/stderr, artifacts) are returned as inert data,
never as something that can itself trigger further action, matching the
port's own docstring.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import time
from io import BytesIO
from typing import Protocol, runtime_checkable
from uuid import uuid4

from cortexward.ports import EgressPolicy, ExecutionResult, ExecutionSpec, ResourceLimits

_WORKSPACE_PATH = "/workspace"
_OUTPUT_PATH = "/output"


@runtime_checkable
class ArtifactStore(Protocol):
    """The subset of `StoragePort` this adapter needs to resolve/produce artifacts.

    A structural protocol, not an import of `cortexward.ports.StoragePort`
    itself: this adapter needs exactly `get_artifact`/`put_artifact`, not
    the finding-event-log half of that port. Depending on the narrower
    shape keeps `cortexward.sandbox` genuinely peer-isolated from
    `cortexward.storage` — any real `StoragePort` adapter (e.g.
    `SqliteStoragePort`) already satisfies this structurally, with zero
    extra glue code required.
    """

    def get_artifact(self, ref: str) -> bytes: ...
    def put_artifact(self, content: bytes) -> str: ...


def _cpu_limit(limits: ResourceLimits) -> float:
    """Approximates a total-CPU-time budget as a consumption-rate cap.

    Docker's `--cpus` throttles how much CPU capacity a container may draw
    upon *while it runs*, not how many CPU-seconds it may consume in
    total — there is no Docker flag for the latter. `wall_clock_seconds`
    (enforced separately, as a hard subprocess timeout) is what actually
    bounds total execution time; this only approximates `cpu_seconds` as a
    rate over that same window, clamped to a sane range so a very short
    `wall_clock_seconds` budget doesn't produce a nonsensically large or
    zero `--cpus` value.
    """
    if limits.wall_clock_seconds <= 0:
        return 1.0
    return max(0.1, min(8.0, limits.cpu_seconds / limits.wall_clock_seconds))


def build_create_argv(spec: ExecutionSpec, *, name: str, docker: str = "docker") -> tuple[str, ...]:
    """The `docker create` argv for `spec`, without starting the container.

    Raises `NotImplementedError` for `EgressPolicy.ALLOW_LIST` (see the
    module docstring) before constructing anything.
    """
    if spec.egress is not EgressPolicy.DENY_ALL:
        raise NotImplementedError(
            f"EgressPolicy.{spec.egress.name} needs per-host network filtering (a custom "
            "Docker network plus firewall/DNS rules) this adapter doesn't implement yet; "
            "only EgressPolicy.DENY_ALL is supported."
        )
    argv: list[str] = [
        docker,
        "create",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp",  # noqa: S108 -- a mount point *inside the container*, not this host's /tmp
        "--memory",
        f"{spec.limits.memory_mb}m",
        "--memory-swap",
        f"{spec.limits.memory_mb}m",
        "--cpus",
        f"{_cpu_limit(spec.limits):.2f}",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--user",
        "1000:1000",
        "--workdir",
        _WORKSPACE_PATH,
    ]
    for key, value in sorted(spec.env.items()):
        argv.extend(["--env", f"{key}={value}"])
    argv.append(spec.image)
    argv.extend(spec.command)
    return tuple(argv)


class DockerSandboxAdapter:
    """Runs `ExecutionSpec`s as ephemeral, isolated Docker containers."""

    isolation_tier = "docker-seccomp"

    def __init__(self, artifacts: ArtifactStore, *, docker: str | None = None) -> None:
        self._artifacts = artifacts
        self._docker = docker

    def _docker_binary(self) -> str:
        if self._docker is not None:
            return self._docker
        resolved = shutil.which("docker")
        if resolved is None:
            raise RuntimeError("docker binary not found on PATH")
        return resolved

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        docker = self._docker_binary()
        argv = build_create_argv(spec, name=f"cortexward-{uuid4().hex[:16]}", docker=docker)
        name = argv[argv.index("--name") + 1]
        bundle = self._artifacts.get_artifact(spec.input_bundle_ref)
        started = time.monotonic()
        try:
            subprocess.run(  # noqa: S603 # nosec B603
                list(argv), capture_output=True, text=True, check=True
            )
            subprocess.run(  # noqa: S603 # nosec B603
                [docker, "cp", "-", f"{name}:{_WORKSPACE_PATH}"],
                input=bundle,
                capture_output=True,
                check=True,
            )
            exit_code, stdout, stderr, timed_out = self._start_and_wait(
                docker, name, spec.limits.wall_clock_seconds
            )
            artifact_refs = self._collect_artifacts(docker, name)
        finally:
            subprocess.run(  # noqa: S603 # nosec B603
                [docker, "rm", "-f", name], capture_output=True, check=False
            )
        return ExecutionResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_seconds=time.monotonic() - started,
            artifact_refs=artifact_refs,
        )

    def _start_and_wait(
        self, docker: str, name: str, wall_clock_seconds: float
    ) -> tuple[int, str, str, bool]:
        try:
            result = subprocess.run(  # noqa: S603 # nosec B603
                [docker, "start", "--attach", name],
                capture_output=True,
                text=True,
                timeout=wall_clock_seconds,
                check=False,
            )
            return result.returncode, result.stdout, result.stderr, False
        except subprocess.TimeoutExpired as exc:
            # Killing *this* subprocess (the `docker` CLI client) does not
            # stop the container server-side -- it must be told to stop
            # explicitly, or it keeps running (and consuming resources)
            # after this method returns.
            subprocess.run(  # noqa: S603 # nosec B603
                [docker, "kill", name], capture_output=True, check=False
            )
            return -1, _decode(exc.stdout), _decode(exc.stderr), True

    def _collect_artifacts(self, docker: str, name: str) -> tuple[str, ...]:
        result = subprocess.run(  # noqa: S603 # nosec B603
            [docker, "cp", f"{name}:{_OUTPUT_PATH}", "-"], capture_output=True, check=False
        )
        # A command that never wrote anything to /output is the common
        # case, not an error -- `docker cp` fails because the path simply
        # doesn't exist inside the container, so this is treated as "no
        # artifacts produced," not propagated as a hard failure.
        if result.returncode != 0 or not result.stdout:
            return ()
        refs: list[str] = []
        with tarfile.open(fileobj=BytesIO(result.stdout), mode="r|*") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                refs.append(self._artifacts.put_artifact(extracted.read()))
        return tuple(refs)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


__all__ = ["ArtifactStore", "DockerSandboxAdapter", "build_create_argv"]
