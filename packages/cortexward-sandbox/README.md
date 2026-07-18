# cortexward-sandbox

`SandboxPort` adapters (MPS §22.4, ADR-0004): isolated dynamic execution, realizing Verification
Ladder rungs 3-4 (dynamic PoC, differential test).

## What exists

- **`DockerSandboxAdapter`** — runs `ExecutionSpec`s as ephemeral, isolated Docker containers via
  the `docker` CLI (no SDK dependency, matching every other subprocess-based adapter in this
  codebase). Registered under the `cortexward.sandbox` entry-point group as `docker`.

```python
from cortexward.sandbox import DockerSandboxAdapter
from cortexward.ports import ExecutionSpec

adapter = DockerSandboxAdapter(my_artifact_store)  # get_artifact/put_artifact, e.g. SqliteStoragePort
result = adapter.execute(ExecutionSpec(command=("pytest",), input_bundle_ref=bundle_ref))
```

MPS §22.4's normative execution contract, followed as literally as a plain `docker` CLI invocation
allows — see the module docstring in `docker_adapter.py` for the full mapping from each contract
line to the exact flags/behavior implementing it:

- No network egress by default (`--network none`); `EgressPolicy.ALLOW_LIST` deliberately raises
  `NotImplementedError` rather than silently granting more (or less) access than requested.
- Read-only root (`--read-only`) with a `--tmpfs /tmp` scratch area and a *named Docker volume*
  (not a tmpfs) mounted at `/output`. `/output` deliberately isn't a tmpfs like `/tmp`: tmpfs
  mounts are torn down the instant a container stops, before this adapter ever gets to `docker cp`
  the produced files back out — confirmed empirically (a real container wrote to `/output` and
  exited 0, yet retrieval always came back empty). A named volume is daemon-managed storage
  independent of any one container's lifecycle, so it survives exactly as long as needed. A fresh
  named volume is root-owned by default, which the synthetic Dockerfile (below) works around by
  pre-creating `/output` with `chown 1000:1000` at build time — Docker copies an image's existing
  directory ownership into a volume the first time it's populated at that mount point, which is
  what actually makes `/output` writable by the unprivileged container user (confirmed
  empirically: without this, the same container that could write to `/tmp` got a `PermissionError`
  writing to `/output`).
- Ephemeral: every container is uniquely named and removed (`docker rm -f`) in a `finally` block;
  the ephemeral image built to deliver the input bundle (below) and the named output volume are
  likewise removed (`docker rmi -f` / `docker volume rm -f`).
- CPU/mem/time caps: `--memory`/`--memory-swap` directly; `wall_clock_seconds` as a hard subprocess
  timeout with an explicit `docker kill` on expiry; `cpu_seconds` approximated as a `--cpus` rate
  clamped to this host's own CPU count (Docker has no native total-CPU-time cap, and some
  daemon/cgroup configurations reject a `--cpus` value above the host's actual count outright).
- **No host mounts**: the `/output` volume above is a *named* Docker volume (`-v <generated-name>:
  /output`), opaque daemon-managed storage, never a real host directory. The input bundle is
  delivered by *building* a small, ephemeral image (`docker build -`, reading a tar stream over
  the daemon API — never a local file on this host) that layers the bundle onto `spec.image` via a
  synthetic, cortexward-authored Dockerfile, and running that image instead of `spec.image`
  directly. Earlier design streamed the bundle into an already-created container via `docker cp -`;
  that was tried and empirically failed against a real daemon (GitHub Actions' runners have one;
  this dev environment doesn't) — Docker unconditionally refuses to copy *into* any container whose
  root filesystem is marked read-only, regardless of destination path. Baking the bundle into an
  image layer at build time sidesteps that restriction while still never touching a host
  bind-mount; produced artifacts are still retrieved via `docker cp` (reading *out* of a container
  has no such restriction).
- Unprivileged user (`--user 1000:1000`), `--security-opt no-new-privileges`, `--cap-drop ALL`.
- Docker's own default seccomp/AppArmor profiles apply automatically (never disabled here).

## Not live-verified in this environment

This environment's `docker` CLI is installed, but its daemon is unreachable (`docker info` fails
to connect to the Docker Desktop engine) — the same category of gap `OllamaAdapter`
(`cortexward-llm`) documents for its own live-server tests. `TestBuildCreateArgv`/`TestCpuLimit`
(pure command-construction logic), the binary-resolution tests, and `TestExecuteMocked` (the full
`execute()` flow — success, nonzero exit, timeout + `docker kill`, artifact collection, guaranteed
cleanup — against a monkeypatched `docker` CLI, the same "mock the external tool's I/O boundary"
convention `BanditScanner`'s/`SemgrepScanner`'s own resilience tests already use) run
deterministically and always pass, reaching 100% coverage without a daemon. `TestLiveDocker`
genuinely exercises a real daemon end to end on top of that (a real container run, egress denial,
bundle round-trip, artifact collection, timeout enforcement, and post-run cleanup) and is skipped
automatically when no daemon is reachable, exercised automatically the moment one is.

## Deliberately not implemented

- **`EgressPolicy.ALLOW_LIST`** — needs a custom Docker network plus firewall/DNS rules to
  genuinely restrict egress to specific hosts; raises `NotImplementedError` rather than
  approximating it unsafely.
- **gVisor/Firecracker tier** (MPS §22.4's "higher assurance" upgrade path) — needs the
  `runsc`/Firecracker runtime installed and configured on the host, unavailable infrastructure in
  any environment this project has verified against.
- **Per-target image selection** — `ExecutionSpec.image` defaults to `python:3.11-slim` (this
  project's own primary supported language); installing a target's own declared dependencies into
  a purpose-built image before executing its tests/PoC is future work once multi-language dynamic
  execution is in scope.
