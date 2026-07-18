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
- Read-only root (`--read-only`) with a `--tmpfs /tmp` scratch area.
- Ephemeral: every container is uniquely named and removed (`docker rm -f`) in a `finally` block.
- CPU/mem/time caps: `--memory`/`--memory-swap` directly; `wall_clock_seconds` as a hard subprocess
  timeout with an explicit `docker kill` on expiry; `cpu_seconds` approximated as a `--cpus` rate
  (Docker has no native total-CPU-time cap — documented, not silently pretended away).
- **No host mounts**: the input bundle is streamed in and any produced artifacts streamed back out
  via `docker cp -` (a tar stream over the daemon API), never a `-v <host path>:...` bind mount.
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
