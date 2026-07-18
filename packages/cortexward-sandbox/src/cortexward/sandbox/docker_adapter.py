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
- **read-only root** — ``--read-only``, with ``--tmpfs /tmp`` and
  ``--tmpfs /output`` scratch areas (a container that can write nowhere at
  all can't produce a PoC's output artifacts).
- **ephemeral, per-run filesystem scrubbed afterward** — every container
  gets a fresh, uniquely-named instance, removed (``docker rm -f``) in a
  ``finally`` block regardless of outcome; the ephemeral image built to
  deliver the input bundle (see below) is likewise removed (``docker
  rmi``).
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
  The input bundle is delivered by *building* a small, ephemeral image
  (``docker build -``, reading a tar stream over the daemon API — never a
  local file on this host) layering the bundle onto ``spec.image`` via a
  synthetic, cortexward-authored ``Dockerfile``, and running that image
  instead of ``spec.image`` directly. This is *not* the original design
  (streaming the bundle into an already-created container via ``docker cp
  -``) — that approach was tried and empirically failed against a real
  daemon: Docker unconditionally refuses to copy *into* any container
  whose root filesystem is marked read-only ("container rootfs is marked
  read-only"), regardless of the destination path, which only surfaced
  once this was exercised against GitHub Actions' real Docker daemon (this
  project's own dev environment has none reachable). Baking the bundle
  into an image layer at build time sidesteps that restriction entirely,
  while still never touching a host bind-mount.
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

import os
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
_DOCKERFILE_PATH = ".cortexward-build/Dockerfile"
"""Reserved path within the synthetic build-context tar (see `_build_context_tar`)."""


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

    The upper clamp is this host's own CPU count, not an arbitrary
    constant: some Docker daemon/cgroup configurations reject a `--cpus`
    value that exceeds the number of CPUs actually available, failing
    `docker create` outright rather than merely capping the effective
    rate.
    """
    if limits.wall_clock_seconds <= 0:
        return 1.0
    ceiling = float(os.cpu_count() or 1)
    return max(0.1, min(ceiling, limits.cpu_seconds / limits.wall_clock_seconds))


def build_create_argv(
    spec: ExecutionSpec, *, name: str, image: str | None = None, docker: str = "docker"
) -> tuple[str, ...]:
    """The `docker create` argv for `spec`, without starting the container.

    `image` overrides `spec.image` — `execute()` passes the ephemeral image
    built from `spec.image` plus the input bundle, never `spec.image`
    directly (that image has no bundle files in it at all). Defaults to
    `spec.image` so callers testing flag construction in isolation don't
    need to go through the build step.

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
        "--tmpfs",
        _OUTPUT_PATH,
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
    argv.append(image if image is not None else spec.image)
    argv.extend(spec.command)
    return tuple(argv)


def _build_context_tar(image: str, bundle: bytes) -> bytes:
    """Merges a synthetic, cortexward-authored Dockerfile with `bundle` into
    one build-context tar, so the bundle's files land inside a real image
    layer (baked in at build time) rather than needing `docker cp` to write
    into an already-`--read-only` container, which Docker's daemon flatly
    refuses (see the module docstring).

    Any bundle member that collides with the reserved Dockerfile path is
    skipped, not merged: the bundle is untrusted input (ADR-0004), and
    letting it supply its own Dockerfile would let a malicious bundle
    inject arbitrary `RUN` build steps with the *daemon's* own network
    access — a build runs before the container's deny-egress policy ever
    applies to anything.
    """
    dockerfile = f"FROM {image}\nCOPY . {_WORKSPACE_PATH}\nWORKDIR {_WORKSPACE_PATH}\n".encode()
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w") as out_tar:
        info = tarfile.TarInfo(name=_DOCKERFILE_PATH)
        info.size = len(dockerfile)
        out_tar.addfile(info, BytesIO(dockerfile))
        if bundle:
            with tarfile.open(fileobj=BytesIO(bundle), mode="r|*") as bundle_tar:
                for member in bundle_tar:
                    if member.name == _DOCKERFILE_PATH or member.name.startswith(
                        ".cortexward-build/"
                    ):
                        continue
                    extracted = bundle_tar.extractfile(member) if member.isfile() else None
                    out_tar.addfile(member, extracted)
    return output.getvalue()


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _run_or_raise(argv: list[str], *, step: str, input: bytes | None = None) -> None:
    """Runs an infrastructure-setup docker command, raising with its stderr on failure.

    Used only for the `build`/`create` steps that must succeed for the run
    to mean anything at all -- unlike `_start_and_wait`, where a nonzero
    exit is the analyzed command's own legitimate result, not an infra
    failure. A bare `subprocess.CalledProcessError` doesn't surface
    `stderr` in its default message, which made an earlier failure of this
    exact call needlessly hard to diagnose from CI logs alone.
    """
    result = subprocess.run(  # noqa: S603 # nosec B603
        argv, input=input, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"{step} failed (exit {result.returncode}): {_decode(result.stderr)}")


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
        bundle = self._artifacts.get_artifact(spec.input_bundle_ref)
        image_tag = f"cortexward-build-{uuid4().hex[:16]}"
        argv = build_create_argv(
            spec, name=f"cortexward-{uuid4().hex[:16]}", image=image_tag, docker=docker
        )
        name = argv[argv.index("--name") + 1]
        started = time.monotonic()
        try:
            _run_or_raise(
                [docker, "build", "-f", _DOCKERFILE_PATH, "-t", image_tag, "-"],
                step="docker build",
                input=_build_context_tar(spec.image, bundle),
            )
            try:
                _run_or_raise(list(argv), step="docker create")
                exit_code, stdout, stderr, timed_out = self._start_and_wait(
                    docker, name, spec.limits.wall_clock_seconds
                )
                artifact_refs = self._collect_artifacts(docker, name)
            finally:
                subprocess.run(  # noqa: S603 # nosec B603
                    [docker, "rm", "-f", name], capture_output=True, check=False
                )
        finally:
            subprocess.run(  # noqa: S603 # nosec B603
                [docker, "rmi", "-f", image_tag], capture_output=True, check=False
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


__all__ = ["ArtifactStore", "DockerSandboxAdapter", "build_create_argv"]
