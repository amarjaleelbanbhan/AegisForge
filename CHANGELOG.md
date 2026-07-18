# Changelog

All notable changes to CortexWard are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **Inconsistent line endings across the whole repository.** No `.gitattributes` ever existed,
  so every file's line ending was whatever the committing machine's editor/tool happened to use
  — a real, confirmed split: 41 CRLF vs. 112 LF `.py` files, 23 CRLF vs. 20 LF `.md` files, and
  more, entirely by accident of which OS last touched each file. Added `.gitattributes` (`* text
  =auto eol=lf`) and renormalized every tracked file with `git add --renormalize .`, verified to
  be a pure line-ending change with no content difference (`git diff -w` shows nothing but the
  new `.gitattributes` file itself).

### Security
- **Symlink-escape fix in file discovery.** `SecretsScanner` and the Python `LanguageProvider`
  both walked scanned/parsed trees with `Path.rglob()`, which only gained a
  `recurse_symlinks=False` default in Python 3.13 — on the 3.11/3.12 this project's own CI
  matrix still supports, a symlink inside a scanned repository (untrusted, adversarial input
  per ADR-0004) pointing outside the intended root would be silently followed, letting a
  crafted repository pull unrelated files on disk into a scan or parse. Both now use
  `os.walk(..., followlinks=False)` plus an explicit `is_symlink()` check on each discovered
  file — version-independent, not reliant on a Python-version-specific default. Verified with
  real symlinked files and directories (skipped automatically in environments without symlink
  privileges). Along the way, deduplicated the identical excluded-directory-names list that had
  drifted into three independent copies (`cortexward-scanners`' two adapters and
  `cortexward-cpg`'s Python provider) into `cortexward.domain.filesystem.EXCLUDED_DIR_NAMES` — a
  plain tuple, not a set, since import-linter's sibling-adapter contracts mean `cortexward.domain`
  is the only shared home available, and iteration order needs to stay deterministic.
- **`pip-audit` now actually gates CI.** The self-audit job's `pip-audit` step silently
  swallowed every finding (`|| echo "::warning::..."`), so it could never fail the build — a
  security control that can't fail isn't a gate. No advisories exist against the current
  locked dependency set, so this was safe to flip to blocking today.
- **Four transitive advisories from the new `semgrep` dependency, confirmed unreachable and
  explicitly ignored.** Adding `SemgrepScanner` pulled in `semgrep`'s hard pins on `click~=8.1.8`
  (`PYSEC-2026-2132`, a command-injection fix in `click.edit()` — this codebase never calls
  `click.edit()` or imports `click` at all, it only invokes the `semgrep` CLI as a subprocess) and
  `mcp==1.23.3` (`CVE-2026-52870`, `CVE-2026-52869`, `CVE-2026-59950` — all three are MCP
  **server**-side transport/handler vulnerabilities; this project never starts an MCP server).
  Neither package has a newer semgrep-compatible pin available yet, so each advisory is ignored
  with `pip-audit`'s own `--ignore-vuln <ID>`, one flag per ID with the reasoning recorded inline
  in `ci.yml` — not a blanket re-widening of the gate flipped to blocking above.

### Fixed
- **Unbounded subprocess hangs.** Neither the `bandit` subprocess (`BanditScanner`) nor the
  `git apply` subprocess (`apply_and_rescan`'s patch-gate verification) had a `timeout=`, unlike
  every network call in this codebase (`OsvScanner`, every `LLMPort` adapter). A hung external
  process could block a scan or gate check indefinitely with no recovery. Both now have an
  explicit, generous-but-bounded timeout (300s for Bandit, 30s for `git apply`) and degrade
  gracefully on expiry — no findings from that scanner, or `None` ("inconclusive") from the gate
  check — rather than propagating `subprocess.TimeoutExpired` and crashing the run.
- **`Dockerfile` shipped a non-functional image.** It only ever installed `cortexward-core`
  standalone and its `CMD` was a placeholder stub predating the `ward` CLI entirely — the
  comment literally said "replaced by the CLI entry point in a later phase," and that phase
  landed without this file ever being revisited. Nothing built or ran it in CI, so this drifted
  silently. Rewritten: the builder stage now copies the whole workspace (workspace-member
  dependencies resolve via `{ workspace = true }` sources, ADR-0005, so a single package can't
  be installed in isolation) and runs `uv sync --frozen --no-dev --no-editable --package
  cortexward-cli`, verified empirically to pull in every transitive workspace dependency
  `cortexward-cli` actually needs as real, non-editable files (not a `.pth` pointing back at
  source, which would break once the runtime stage copies only `/opt/venv`). `ENTRYPOINT
  ["ward"]` replaces the old stub `CMD`. A new `docker-build` CI job (Docker isn't available in
  this development environment, so GitHub Actions' own runners are the only place this can be
  verified) builds the image and smoke-tests it for real: `ward --help` runs, the container
  runs as the unprivileged `cortex` user, and `ward scan` against a mounted, deliberately
  vulnerable fixture actually reports the finding. A `.dockerignore` was also added — none
  existed, so every build sent `.git`, `.venv`, and every cache directory into the build context.

### Changed
- **Project renamed from AegisForge to CortexWard.** AegisForge collided with dozens of existing
  GitHub projects, several directly in the same space; CortexWard is confirmed clean across
  GitHub, PyPI, and npm. GitHub repo renamed (About description + topics set); packages renamed
  to `cortexward-{core,cpg}`; the Python namespace moved from `aegisforge.*` to `cortexward.*`
  throughout; the derived CLI shorthand `aegis` → `ward`. No functional changes.

### Added
- **`DockerSandboxAdapter`** (`cortexward-sandbox`, new workspace package): the first `SandboxPort`
  (MPS §22.4, ADR-0004) implementation. Follows the normative execution contract as literally as a
  plain `docker` CLI invocation allows: `--network none` by default (`EgressPolicy.ALLOW_LIST`
  raises `NotImplementedError` rather than approximating it unsafely), `--read-only` root with
  a `--tmpfs /tmp` scratch area and a named Docker volume (not a tmpfs — those are torn down the
  instant a container stops, before retrieval could ever succeed) mounted at `/output`, ephemeral
  per-run containers (and the image built to deliver the input bundle, and the named output
  volume) always removed, `--memory`/`--memory-swap` limits,
  `wall_clock_seconds` as a hard subprocess timeout with an explicit `docker kill` on expiry, and
  genuinely **no host mounts** — the input bundle is delivered by *building* a small, ephemeral
  image (`docker build -`, a tar stream over the daemon API) layering the bundle onto `spec.image`
  via a synthetic Dockerfile, never a bind mount. `ExecutionSpec` gained an `image` field (default
  `python:3.11-slim`) the port previously had no way to express. Not live-verified in this
  environment (Docker's CLI is installed but its daemon is unreachable, confirmed via `docker
  info`'s connection error) — deterministic tests always run, reaching 100% coverage without a
  daemon; a `TestLiveDocker` class exercises a real daemon end to end and skips automatically
  otherwise, matching `OllamaAdapter`'s own `TestLiveOllama` pattern.
- **Fixed a real bug `TestLiveDocker` caught the moment CI actually had a reachable Docker daemon
  (GitHub Actions' runners do; this project's own dev environment doesn't).** The original
  `DockerSandboxAdapter` design streamed the input bundle into an already-`--read-only`-created
  container via `docker cp -`; Docker's daemon unconditionally refuses to copy *into* any container
  whose root filesystem is marked read-only ("container rootfs is marked read-only"), regardless of
  destination path — an error only a real daemon could ever surface. Fixed by building a small,
  ephemeral image layering the bundle onto `spec.image` (`docker build -`) instead, and running
  that image; `_cpu_limit`'s `--cpus` upper clamp was also lowered from a hardcoded `8.0` to this
  host's own `os.cpu_count()`, since some Docker/cgroup configurations reject a `--cpus` value
  above the host's actual count outright. `docker create`/`docker build` failures now raise with
  the daemon's actual decoded `stderr` text instead of a bare `subprocess.CalledProcessError`,
  which had made the original failure needlessly hard to diagnose from CI logs alone.
- **Fixed a second real bug the same CI daemon caught immediately after the first fix landed:**
  `/output` was originally a `--tmpfs` mount, but tmpfs mounts are torn down the instant a
  container stops — a real run wrote its output file and exited 0, yet artifact retrieval came
  back empty every time, since `_collect_artifacts()`'s `docker cp` only runs after the container
  has already finished. Fixed by mounting `/output` as a named Docker volume instead (still no
  host mount — a named volume is opaque, daemon-managed storage), which survives independently of
  the container's own lifecycle; the volume is now also removed in the cleanup `finally` block.
- **Fixed a third real bug the same CI daemon caught immediately after the second fix landed:**
  a freshly-created named Docker volume is root-owned by default, so the unprivileged `1000:1000`
  container user got `PermissionError` writing to `/output` even after the tmpfs-vs-volume fix
  above — `/tmp` worked fine (tmpfs mounts default to world-writable `mode=1777`), `/output`
  didn't. Fixed by having the synthetic Dockerfile pre-create `/output` and `chown 1000:1000` it at
  build time: Docker copies an image's existing directory ownership into a named volume the first
  time it's populated at that mount point, which is what actually makes the volume writable by the
  container's own user.
- **`LangGraphOrchestrator`** (`cortexward-orchestrator`): the LangGraph-backed `OrchestratorPort`
  adapter ADR-0002 named as its reference ("LangGraph is one adapter behind that port"). Runs the
  exact same `Agent` sequence `AgentOrchestrator` does, as a `langgraph.graph.StateGraph` instead
  of a plain Python loop — no behavior change. LangGraph's own types never escape the module's
  boundary. A real mypy/LangGraph-stub interaction surfaced and was worked around (documented
  inline): `StateGraph.add_node`'s generic overload set fails to match a
  `Callable[[State], State]`-typed value but resolves a literal nested `def` without issue.
  100%-covered, mirroring `AgentOrchestrator`'s own test suite to prove behavioral equivalence.
- **`SqliteStoragePort`** (`cortexward-storage`, new workspace package): the first `StoragePort`
  (MPS §17.1/§19, ADR-0008) implementation, closing a gap `SqliteRepositoryMemory`'s own docs used
  to cite as needing "a port-level design decision this project hasn't made yet." That decision
  turned out to be small and inferable, not an open product question: `FindingEvent` gained a
  `finding` field carrying the full detected `Finding` snapshot on `DETECTED` events — the one
  piece of data ever missing to replay a finding's materialized state from its own log.
  `materialize_finding()` (`cortexward.ports`) is the resulting pure replay function, shared by
  every `StoragePort` adapter, folding `EVIDENCE_ATTACHED`/`ASSESSED`/`PATCH_PROPOSED`/
  `SUPPRESSED` events onto the `DETECTED` snapshot via the domain's own `with_evidence`/
  `apply_assessment`/`with_state` — nothing invented, all grounded in vocabulary the domain model
  already defines. `SqliteStoragePort` persists only the append-only log (stdlib `sqlite3`);
  `list_findings(run_id)` reads a finding's detected-run identity from `Finding.provenance.run_id`
  rather than adding a redundant column. Registered under `cortexward.storage` as `sqlite`.
  100%-covered.
- **`ward bench run/compare/report`** (`cortexward-cli`) plus a versioned golden dataset
  (`cortexward-eval/datasets/golden/v1`, MPS §4.1's "novel" split): the evaluation harness
  contract MPS §20.1 names. `bench run <dataset-manifest> --output FILE` scans every registered
  scanner over the dataset via `cortexward.eval.harness.run_bench()` (new `cortexward.eval.dataset`
  loader), writing a `RunManifest` plus a `.matches.json` sidecar of per-example detection
  outcomes (kept out of `RunManifest` itself, which only ever carries aggregate metrics per
  evaluation-framework.md §5's documented shape). `bench compare <a> <b>` reports metric deltas
  plus McNemar's test when both runs' sidecars share example ids. `bench report <manifest>
  [--format md,json]` renders Markdown/JSON. The golden dataset's 10 examples (8 vulnerable, 2
  true-negative) each have ground truth transcribed from a real `ward scan` run against the exact
  fixture, not hand-guessed — verified end-to-end with a perfect precision=1.000/recall=1.000/
  f1=1.000 `ward bench run`. Fixed a real cross-platform bug along the way:
  `cortexward.eval.metrics._locations_overlap` compared `SourceLocation.path` strings verbatim, so
  a portable (forward-slash) dataset path never matched a scanner-emitted, OS-native
  (backslash-on-Windows) path, silently zeroing every metric on Windows. Contamination-controlled
  splits (memorized/post-cutoff/mutated) remain unbuilt — a "mutated" split needs
  vulnerability-preserving mutation operators, which the MPS's own Open Questions (§30) name as
  unresolved. 100%-covered.
- **`CycloneDxVexReporter`** (`cortexward-reporters`): the VEX output MPS FR-7 requires
  ("CycloneDX-VEX/CSAF-VEX"). Renders a CycloneDX 1.5 VEX document per `Finding`, computing
  `analysis.state` by calling `cortexward.domain.verification.assess()` (the same pure function
  everything else in this framework uses) and mapping the resulting `VexStatus` onto CycloneDX's
  own enum. Registered as `cyclonedx-vex`; selectable via `ward scan --format cyclonedx-vex` with
  zero CLI code changes. 100%-covered.
- **`ward scan --engine {agent,langgraph}`**: `build_pipeline()` gained an `engine` parameter
  selecting which `OrchestratorPort` runs the agent sequence when an LLM is configured, closing the
  gap `LangGraphOrchestrator`'s own changelog entry above left open ("not wired into
  `build_pipeline()`/`ward scan`"). Default (`"agent"`) is byte-for-byte the prior behavior.
  100%-covered.
- **Trust-boundary modeling** (`Threat.crosses_trust_boundary`, MPS Phase 5): MPS §22.1's
  untrusted-zone/trusted-control-plane split, generalized from describing CortexWard's own
  architecture to an analyzed target's — a known entry point stands in for that target's untrusted
  zone, and this asks the strictly stronger question attack-surface mapping doesn't: does *data*
  from there actually flow into this location, via `CodeGraph.taint()` (built in Phase 2,
  previously unused outside `cortexward-cpg`'s own tests). A path a declared sanitizer lies on
  does not count as a crossing. `cortexward.agents.reachability.crosses_trust_boundary()` and
  `ThreatModel.boundary_crossings` mirror the existing `is_reachable_from_entrypoint()`/`.exposed`
  pair exactly. 100%-covered.
- **Phase 3 — Semgrep adapter, closing the last open item in Phase 3.** `SemgrepScanner`
  invokes the real `semgrep` binary against `semgrep_rules/`, a small rule pack authored in this
  repository and bundled with the package — never `--config=auto` or a registry shorthand, both
  of which need network access to semgrep.dev and were this adapter's long-documented blocker.
  Verified fully offline: built a real wheel, confirmed the rule YAML files are actually bundled
  inside it. Four rules, each targeting a pattern Bandit's AST matching doesn't reach: SSRF
  (CWE-918, taint mode), Flask `render_template_string` server-side template injection (CWE-79,
  taint mode), hard-coded credentials by variable name (CWE-798, complements `SecretsScanner`'s
  entropy-based detection), and JWT signature-verification bypass (CWE-347, new to the STRIDE
  table). Every rule was authored and empirically verified — fires on a real vulnerable fixture,
  silent on a real safe one — before being committed, enforced going forward by
  `TestBundledRules`. 100%-covered, including the same resilience tests (timeout, missing
  binary, malformed JSON) every other scanner adapter here has. A real bug this testing
  surfaced: `_location_for` used `result["path"]` (bracket access), unlike every other field in
  this codebase's untrusted-scanner-output handling (ADR-0004) — fixed to degrade gracefully
  when a result has no `path` instead of raising `KeyError`.
- **`SqliteRepositoryMemory`** (`cortexward-agents`): a persistent `RepositoryMemory`, closing
  `InMemoryRepositoryMemory`'s documented "lost when the process exits" limitation. Uses stdlib
  `sqlite3` only. `RepositoryMemory`'s three-method protocol is small and fully self-contained,
  unlike `StoragePort`'s general event-sourced finding log (whose `FindingEvent` model has no
  field for a finding's own core data — a real adapter for *that* needs a port-level design
  decision this project hasn't made yet) — so this closes a real gap without waiting on that
  broader decision. Supports both `:memory:` (the default, matching `InMemoryRepositoryMemory`'s
  ephemeral-by-default ergonomics) and a file path for genuine cross-process persistence; a
  context manager (`with SqliteRepositoryMemory(...) as memory:`). 100%-covered, including a
  real round-trip through two separate connections to the same file confirming persistence
  actually survives a close/reopen, not just a single in-process session.
- **`GitHubVCSAdapter`** (`cortexward-vcs`, new workspace package): the first `VCSPort`
  implementation — the port itself was already defined (Phase 1's port catalog work), but no
  adapter existed. Calls GitHub's REST API v3 via `urllib.request` (no `PyGithub` dependency);
  `checkout` shells out to a real `git` subprocess, reusing `apply_and_rescan`'s own discipline
  (`shutil.which`-resolved, no shell, a bounded timeout, and — new here — redaction of the
  embedded access token from any git stderr surfaced in an exception). Registered under the
  `cortexward.vcs` entry-point group as `github`; a new import-linter contract holds it to the
  same peer-isolation standard as the other adapter families. 100%-covered: `checkout` against a
  real local git repository, the REST calls against GitHub's documented schema (deterministic,
  no network — not live-verified, no credentials in this environment, the same caveat
  `AnthropicAdapter`/`GeminiAdapter` carry), and a genuine entry-point-discovery check. This is
  the adapter layer only — a GitHub App (JWT/installation-token exchange, a webhook receiver,
  automated end-to-end PR review) is a separate, larger integration this session deliberately
  didn't attempt, since registering an actual GitHub App is an owner-account action this project
  can't make unilaterally.
- **Phase 8 — VS Code extension** (`integrations/vscode/`), this monorepo's first TypeScript/
  Node subproject. **CortexWard: Scan Workspace** runs `ward scan --fail-on none --format sarif`
  (no LLM, matching `ward baseline`/`ward threat-model`) and publishes results as real
  `vscode.Diagnostic`s grouped by file; **CortexWard: Clear Findings** clears them.
  `cortexward.wardPath` is the only setting.
  - SARIF parsing (`src/sarif.ts`) and the subprocess wrapper (`src/scan.ts`) are
    VS-Code-API-independent, unit-testable without the Extension Host; every field is accessed
    defensively since SARIF is untrusted, externally-produced input.
  - 18 unit tests + 4 integration tests running inside a real, downloaded VS Code Extension Host
    (`@vscode/test-electron`), plus a manual end-to-end run against the real `ward` binary
    (not a fixture) confirming a genuine subprocess scan produces correctly parsed diagnostics.
    Packaging into a `.vsix` verified via `@vscode/vsce`.
  - Caught and fixed a real bug this verification surfaced: `package.json`'s `main` pointed at
    `./out/extension.js`, but the actual compiled path is `./out/src/extension.js` — the
    extension would have failed to activate for every real user despite compiling and
    unit-testing cleanly. Only the integration test, which actually loads the extension inside a
    real Extension Host, caught it.
  - Found and fixed a transitive dev-dependency vulnerability (`mocha` → `serialize-javascript`,
    RCE + DoS advisories) via an npm `overrides` entry, rather than downgrading mocha as `npm
    audit fix --force` suggested.
  - New CI workflow (`.github/workflows/vscode-extension.yml`, path-filtered to
    `integrations/vscode/**`): compiles, unit-tests, and integration-tests (via `xvfb-run` on
    Linux, natively on Windows) on both `ubuntu-latest` and `windows-latest`, then verifies
    packaging.
- **`actionlint` in CI.** Every `.github/workflows/*.yml` file (and `action.yml`) is now
  statically checked on every push/PR — catches the class of bug this session hand-verified
  manually throughout (unsafe `${{ inputs.* }}` interpolation directly into a shell script,
  wrong context references, invalid expressions) automatically instead. Verified locally against
  this repo's own workflow files before adding the CI job: zero findings.
- **Dependabot** (`.github/dependabot.yml`): weekly automated update PRs across every ecosystem
  this repo actually has — `uv` (`pyproject.toml`/`uv.lock`, GA in Dependabot since March 2025),
  `github-actions` (workflow action versions), `docker` (the root `Dockerfile`), and
  `devcontainers` (`.devcontainer/devcontainer.json`'s base image). Python dependency updates are
  grouped into one PR per week rather than one-per-package to keep review manageable.
- **Phase 8 — GitHub Action.** `action.yml` (repo root): a composite action wrapping `ward scan`.
  Checks out CortexWard itself at a pinned ref (`cortexward-ref`, default `main`) into a side
  path, `uv sync`s it, and runs `ward scan` against the calling repository's own checkout — no
  PyPI publish needed. Inputs are threaded through `env:` variables, never interpolated directly
  into the shell script, avoiding the standard GitHub Actions shell-injection pitfall. Results
  upload via `github/codeql-action/upload-sarif` into the calling repo's Security tab.
  Self-tested end to end on this repo's own CI
  (`.github/workflows/action-smoke-test.yml`, `uses: ./` pinned to the exact commit under test):
  one job scans a known-clean package (asserts exit 0), another scans a deliberately vulnerable
  fixture (asserts exit 1 and a produced SARIF file).
- **Phase 5 (in progress) — Threat & architecture reasoning: STRIDE threat modeling.** Grounded
  on existing scanner findings, not a new detection capability.
  - `Threat`/`ThreatModel` (`cortexward.domain.threat_model`) reclassify a `Finding` under
    STRIDE via `stride_categories_for(cwe)`, a CWE→STRIDE lookup table covering every CWE this
    project's own scanners can actually produce plus common real-world-CVE CWEs. A CWE absent
    from the table yields an empty category set — never a guessed one.
  - `Threat.reachable_from_entrypoint` (attack-surface mapping) reuses the exact control-flow
    reachability query `VerifierAgent` already performs for `REACHABILITY_PROOF` evidence,
    extracted into `cortexward.agents.reachability.is_reachable_from_entrypoint()` so both share
    one implementation; `VerifierAgent` now delegates to it with no behavior change (full
    existing test suite passes unmodified).
  - `build_threat_model()` (`cortexward.agents.threat_model`) is deliberately not an `Agent` —
    STRIDE classification and reachability are both deterministic, so it needs no LLM.
    `build_threat_model_for()` (`cortexward.orchestrator.threat_model`) mirrors `build_pipeline`'s
    role (scan → optionally build a `CodeGraph` → classify), keeping `cortexward-cli` decoupled
    from `cortexward-agents` directly, same as `build_pipeline` already does.
  - `ward threat-model <path>` wires it into the CLI: JSON to stdout or `--output FILE`,
    `--language`, `--reachability/--no-reachability`. No LLM flags, matching `ward baseline`.
  - 100%-covered, including real end-to-end coverage: a genuine command-injection fixture, the
    real `BanditScanner`, and a real CPG proving reachability from an
    `if __name__ == "__main__":` guard.
- **Phase 8 (in progress) — Delivery surfaces: the `ward` CLI**, pulled forward from strict phase
  order to close out `ci.yml`'s own long-standing dogfood-job note ("this job is replaced once
  cortexward-scanners exists, at which point `ward scan .` runs here") now that scanners and the
  orchestrator both exist.
  - New workspace package `cortexward-cli`, depending on `cortexward-orchestrator` and
    `cortexward-reporters`.
  - `ward scan <path>` wires `default_scanners()` → `SequentialOrchestrator` → `SarifReporter`
    into a runnable tool: SARIF to stdout or `--output FILE`, `--language` filtering, `--fail-on
    {none,low,medium,high,critical}` controlling the exit code (default `high`).
  - **Not wired into `ci.yml`**: `ward scan packages` currently flags known false positives in
    this repo's own test fixtures (e.g. the deliberately fake secret literals in the
    detect-secrets adapter's own test suite) that a findings-suppression/baseline mechanism would
    need to mark accepted first — the dogfood job's comment is updated to reflect this, but it
    still runs bandit directly rather than `ward scan`.
  - 100%-covered via `typer.testing.CliRunner`, including real `BanditScanner`/`SecretsScanner`
    runs against fixtures (no mocking) and explicit tests for the `main()`/`__main__` entry points.
  - **`ward scan --llm-provider`**: opts into `cortexward.agents.AgentOrchestrator` instead of
    `SequentialOrchestrator`, so findings carry real LLM verification and control-flow-
    reachability evidence rather than just raw scanner output. `--llm-provider`/`--llm-model`/
    `--llm-api-key`/`--llm-api-key-env`/`--llm-base-url` configure a provider directly (mirroring
    `LLMProviderConfig`'s fields); `--llm-config <path>` loads the same thing from a YAML file via
    the already-existing `cortexward.llm.load_llm_config`, and is mutually exclusive with
    `--llm-provider` (`typer.BadParameter` if both are given). `--reachability`/`--no-reachability`
    controls whether `build_code_graphs()` runs. With no LLM flags given, `scan`'s behavior is
    unchanged byte-for-byte from before this — the agent pipeline is opt-in, never a silent
    default, since it needs a real LLM backend to be worth the added latency/cost. New
    `cortexward-cli` dependencies: `cortexward-agents`, `cortexward-llm`. `SarifReporter`'s
    `properties.state` field reflects the richer verification outcome the agent pipeline produces;
    the full evidence list isn't serialized into SARIF yet (documented as deferred, not silently
    dropped — see `SarifReporter`'s own module docstring). 100%-covered: deterministic tests for
    every validation-error path (missing model, invalid provider, config+provider both given,
    missing/malformed config file) plus a genuine end-to-end CLI invocation against a real local
    Ollama server and a real Bandit finding — skipped when no local Ollama server is reachable,
    matching the same `TestLiveOllama`-style pattern used throughout this codebase.
  - **`ward scan --format`**: selects the `ReporterPort` to render via the plugin registry
    (`registry_for(PluginGroup.REPORTERS)`, the same discovery pattern `default_scanners()`
    already used for scanners) instead of a hardcoded `SarifReporter()` — `sarif` (default) or
    `cortexward-json` (see the `cortexward-reporters` entry below), and any future reporter is
    selectable with zero CLI code changes. An unknown `--format` value raises `typer.BadParameter`
    via the registry's own `PluginNotFoundError`, listing what's actually registered. 100%-covered.
  - **`build_pipeline()`** (`cortexward.orchestrator.pipeline`, new module): extracted from what
    was `ward scan`'s own private `_build_orchestrator()` helper, since the REST API (this
    phase's next surface) needs to make the identical "`SequentialOrchestrator` or
    `AgentOrchestrator`?" decision and shouldn't duplicate it. `cortexward-orchestrator` gains
    `cortexward-agents`/`cortexward-llm` dependencies for this — a deliberate, anticipated move
    (the package's own import-linter contract comment already noted "cpg/llm/reporters are
    expected as agent-driven capabilities land"). `cortexward-cli` in turn **drops** its direct
    `cortexward-agents` dependency: it now only knows about `OrchestratorPort` via
    `build_pipeline()`, not the concrete agent-framework types. Pure refactor, zero behavior
    change — every existing CLI test passes unmodified. 100%-covered.
  - **`ward scan --baseline`/`ward baseline`**: a findings baseline/suppression mechanism
    (`cortexward.cli.baseline`), closing the gap the `--not-wired-into-ci.yml` note above left
    open. `ward baseline <path> [--output cortexward-baseline.json] [--language ...] [--reason
    TEXT]` runs the plain scanner pipeline (deliberately no LLM flags — a baseline records what
    the scanners themselves find today, not an LLM-influenced verification outcome) and writes
    every finding's fingerprint to a JSON file: `{"suppressions": [{"fingerprint", "rule_id",
    "path", "reason"}]}`. `ward scan --baseline FILE` excludes any finding whose fingerprint
    appears in the baseline from both the rendered report and the `--fail-on` exit-code check.
  - **`fingerprint_for()` relocated** from `cortexward.agents.memory` to the new
    `cortexward.domain.fingerprint` module: it turned out to be a domain-level identity concept
    (a stable hash of `rule_id|path:line|cwe`), not agent-specific — `RepositoryMemory`'s
    suppression tracking and this new CLI baseline feature need the exact same fingerprint
    without the CLI needing a dependency on the whole agent framework. `cortexward.agents`
    re-exports it for backward compatibility. 100%-covered: the full behavioral suite moved to
    `cortexward-core`'s `test_fingerprint.py`; `cortexward-agents`' own test now just confirms the
    re-export matches the domain implementation.
  - Fixed a real, pre-existing cross-platform bug this surfaced: `SecretsScanner` constructed
    `SecretsCollection()` with no `root`, so detect-secrets computed each secret's reported path
    via `os.path.relpath(secret.filename, os.getcwd())` — correct on Linux (CI), but raising
    `ValueError` on Windows whenever the scanned root and the process's cwd sit on different
    drives (e.g. a project on `D:` scanned from a shell whose cwd is elsewhere). Fixed by passing
    `root=str(resolved_root)` into `SecretsCollection` explicitly. Found via a genuine baseline
    round-trip test failure, not a synthetic drive-mismatch test.
  - 100%-covered, including a real fixture round-trip: generate a baseline from a vulnerable
    fixture, confirm `--baseline` suppresses exactly that finding while new findings introduced
    afterward still trip `--fail-on`.
  - **`ci.yml`'s dogfood job now runs `ward scan` on itself**, replacing the standalone
    `uvx bandit -r packages/*/src -x "*/tests/*"` step: a bash loop invokes `ward scan
    "$pkg/src" --baseline cortexward-baseline.json --fail-on high` once per `packages/*/src`
    (`ward scan` takes one root at a time), so the same scope now runs the full multi-scanner
    pipeline (bandit + detect-secrets + OSV) instead of bandit alone. `cortexward-baseline.json`
    (repo root) is `{"suppressions": []}` — this repo's only known false positives (fake
    secrets, `shell=True` examples) live in test fixtures, out of scope for a `src`-only scan, so
    nothing needs suppressing today. Verified locally with the exact CI loop before committing.
- **Phase 8 (in progress) — Delivery surfaces: the REST API.** A v1 slice of MPS §20.2's full
  contract, new workspace package `cortexward-server` (depends on `cortexward-orchestrator` and
  `cortexward-llm`, `fastapi`).
  - **`POST /v1/scans`** (202 Accepted), **`GET /v1/scans/{id}`** (poll status),
    **`GET /v1/scans/{id}/findings`** (list results — the full `Finding` shape, evidence
    included, unlike SARIF). The request body mirrors `ward scan`'s own CLI flags
    (`root`/`languages`/`llm_provider`/`llm_model`/`llm_api_key(_env)`/`llm_base_url`/
    `reachability`) and reuses `cortexward.orchestrator.build_pipeline()`, so a scan behaves
    identically whether it's driven from the CLI or the API — the exact same code this session's
    CLI refactor extracted for this purpose.
  - **`JobStore`** (`cortexward.server.jobs`): a thread-safe, in-memory, single-process job
    store — a `Job` stays a frozen value (matching `Finding`/`RunState`'s functional-update
    style), replaced under a lock on each status transition rather than mutated in place. No
    persistence (`StoragePort` has no adapter yet) and no cross-process sharing; documented as a
    genuine v1 limitation, not overlooked. Jobs run via FastAPI's `BackgroundTasks`, which
    Starlette runs in a worker thread for a synchronous function — verified empirically (not
    assumed) that `TestClient` executes a job to completion before a request returns, so tests
    need no polling loop.
  - **Deliberately not implemented**, and documented as such rather than silently missing:
    authentication, rate-limiting, per-finding `POST /v1/findings/{id}/verify`/`fix` (need a
    persisted, independently-addressable finding store), `GET /v1/runs/{id}/manifest`
    (`RunManifest` isn't wired to live scans, only the offline benchmark harness), and
    `POST /v1/webhooks/{provider}` (needs a `VCSPort` adapter, none exist yet). `POST /v1/scans`
    accepts an arbitrary filesystem `root` path on the server with no access control — a
    single-tenant, trusted-caller tool today, matching `ward scan`'s own CLI trust model, not
    something to expose on an untrusted network without adding real authentication and path
    scoping first.
  - Caught and fixed a real Python footgun while building this: `cortexward/server/__init__.py`
    originally did `from cortexward.server.app import app`, which — because the submodule is
    also named `app` — silently rebinds the `cortexward.server.app` *attribute* on the package
    object from "the submodule" to "the FastAPI instance." `import cortexward.server.app as x`
    resolves through that attribute chain, so `x` would silently become the FastAPI instance
    instead of the module. Verified this would actually happen (not just a theoretical concern)
    before removing the re-export.
  - 100%-covered via FastAPI's `TestClient` against the real app (real `BanditScanner`, no
    mocking), plus a genuine end-to-end run against the real local Ollama server — skipped when
    none is reachable, matching the `TestLiveOllama` pattern used throughout this codebase.
  - **`ward serve`**: wires the REST API into the CLI — `uvicorn.run("cortexward.server.app:app",
    host=..., port=..., reload=...)`. `cortexward-cli` gains `cortexward-server` and `uvicorn` as
    hard dependencies (not an optional extra) so the command genuinely works, not just imports
    cleanly. Verified with a real running process: started `ward serve`, `POST`ed a real scan
    request over an actual HTTP connection, polled it to `"completed"`, then stopped the exact
    process by its PID (not a blanket `taskkill`, which the harness itself correctly refused as
    too broad). 100%-covered — the CLI test monkeypatches `uvicorn.run` itself so tests don't
    block on binding a real port.
- **Phase 7 (in progress) — Patch generation: gate verification.** `RepairAgent`/`ReviewerAgent`
  already covered minimal-diff generation and advisory review (see Phase 4 below); this adds the
  gate verification MPS §16 requires before `Patch.is_validated`.
  - **`apply_and_rescan()`** (`cortexward.agents.patch_gates`): Gates A ("applies cleanly") and C
    ("rescan clean") — the two of the four gates that don't need sandboxed code execution.
    Copies only the files a `Patch` touches into a scratch directory, applies the diff via
    `git apply` (a trusted external tool, resolved through `shutil.which` rather than a bare
    `"git"` argv entry — never the analyzed project's own code), and re-runs the same scanners
    against the patched copy to check whether the original finding's `rule_id` still appears.
    Only a genuine positive/negative rescan result ever sets `Patch.rescan_clean`; an
    inconclusive outcome (patch didn't apply, referenced files missing, `git` unavailable) leaves
    it untouched. The diff comes from an LLM (`RepairAgent`), treated as untrusted input per
    ADR-0004's spirit: `Patch.files_changed` entries are validated against `..` traversal and
    absolute/drive-letter paths with OS-independent string logic (deliberately not
    `pathlib.Path.is_absolute()`, whose answer for a Windows drive-letter path depends on which
    OS the check itself runs on) before anything is read from the real project root or written
    to the scratch directory.
  - **`RunState.with_patches_updated()`**: a replace-semantics counterpart to the existing
    append-only `with_patches()`, needed so `ReviewerAgent` can record a gate verdict on the
    patches `RepairAgent` already proposed this run rather than appending duplicates.
  - **`ReviewerAgent`** now takes an optional `scanners` — when given (as `default_agents()`
    does, reusing the same scanner list `ScannerAgent` uses), it calls `apply_and_rescan()` for
    each patch before its existing advisory LLM review, which is unchanged: the LLM verdict is
    still a `RunState` note only, never a `Patch` gate field, keeping the same LLM-insufficiency
    discipline `VerifierAgent` already enforces for findings.
  - `Patch.is_validated` still requires `tests_pass`/`rescan_clean`/`exploit_neutralized` all
    truthy; Gates B ("existing tests pass") and D ("original PoC neutralized") need to execute
    the analyzed project's own code, which needs Phase 6's `SandboxPort` and doesn't exist yet —
    a patch can reach `rescan_clean = True` through this work and still correctly have
    `is_validated = False` until then. 100%-covered using the real `git` binary and the real
    `BanditScanner` (no mocking — this module's entire job is applying a real diff and
    re-running a real scanner).
- **Phase 4 (in progress) — Agent framework: LLM abstraction.**
  - New workspace package `cortexward-llm`, depending on `cortexward-core`.
  - **`OllamaAdapter`** (`cortexward.llm.ollama_adapter.OllamaAdapter`): implements `LLMPort`
    against a local Ollama server's `/api/chat`, over stdlib `urllib` (no new HTTP dependency,
    mirroring the OSV scanner's approach). Needs no API key — the only one of the MPS's six
    required v1 adapters buildable and genuinely integration-testable without provider
    credentials. `cost_estimate` is always `0.0` (local inference has no per-token billing);
    `count_tokens` is a documented ~4-chars-per-token heuristic. A connection failure raises
    `OllamaError` rather than degrading silently, unlike a scanner's "one unreachable source
    shouldn't abort the scan" — a caller invoking an LLM adapter is relying on getting a real
    completion back. 100%-covered: deterministic monkeypatched request/response-mapping tests
    (always run) plus a `TestLiveOllama` class that exercises a real local server when reachable
    and skips otherwise (this project's CI has no Ollama installed, unlike OSV.dev's public API).
  - **`ModelRouter`** (`cortexward.llm.router.ModelRouter`): the declarative task-class →
    model-tier → adapter router from MPS §14 — `TRIAGE`/`REASONING`/`PATCH_GENERATION` route to
    `CHEAP`/`STRONG` by default, config-driven and overridable per run (`tier_overrides`), with
    `offline=True` pinning every task class to the local tier. Fully unit-tested against fake
    `LLMPort` adapters, no network dependency.
  - Registered under the `cortexward.llm` entry-point group; a new "LLM adapters do not depend on
    other adapters or interfaces" import-linter contract mirrors the existing adapter-family ones.
  - **`SequentialOrchestrator`** — new workspace package `cortexward-orchestrator`, depending on
    `cortexward-core` and `cortexward-scanners`. Implements `OrchestratorPort`: runs every
    configured `ScannerPort` in sequence, then correlates the results into `Finding`s via
    `cortexward.scanners.correlate`. No LLM/agent reasoning yet — the reference in-process
    orchestrator "run every scanner and merge the results" needs before agent-driven planning.
    `default_scanners()` auto-discovers every scanner registered under `cortexward.scanners`, so a
    full scan → correlate → SARIF pipeline runs end to end with no hardcoded scanner list. Unlike
    its peer adapters, deliberately *not* isolated from `cortexward.scanners` (coordinating other
    adapters is its job); a narrower "does not depend on interface/delivery layers" contract keeps
    it from reaching into the not-yet-built CLI/server/SDK. 100%-covered, including a real
    end-to-end run with `BanditScanner`/`SecretsScanner` against a fixture with a known
    vulnerability and secret.
  - **`cortexward-agents`** (new workspace package): the agent-framework foundation the seven
    agents (Planner, Scanner, Verifier, Repair, Reviewer, Coordinator, Memory) build on. `RunState`
    (`cortexward.agents.state`) — a frozen dataclass carrying one run's findings/patches/notes,
    updated only via `dataclasses.replace()`-based `with_*` methods (`with_findings` replaces;
    `with_patches`/`with_note`/`with_completed`/`with_round_complete` append), mirroring the
    `Finding.with_evidence()`/`with_state()` pattern already established in the domain core (MPS
    §13: "agents are stateless functions over a shared, typed `RunState`"). `Agent`
    (`cortexward.agents.protocol`) — a `runtime_checkable` `Protocol` (`name`, `run(state) ->
    state`). `ResilientLLM` (`cortexward.agents.resilient_llm`) — wraps an ordered `LLMPort`
    sequence with per-adapter retry (exponential backoff, injectable `sleep` for deterministic
    tests) and cross-adapter fallback, raising `AllAdaptersFailedError` only once every adapter is
    exhausted. `run_tool_loop` (`cortexward.agents.tools`) — the bounded tool-calling round trip
    (send request → execute any `tool_calls` → append `TOOL` messages → resend, capped by
    `max_iterations`), documented as not universal since not every backend populates `tool_calls`
    structurally. `load_prompt` (`cortexward.agents.prompt_loader`) — loads versioned, hashed
    prompt templates bundled as real package data under `cortexward/agents/prompts/<name>/<version>
    .md` (verified via an actual `uv build` + wheel inspection, not assumed), covering all five v1
    agent prompts (planner, verifier, repair, reviewer, coordinator). Memory abstractions
    (`cortexward.agents.memory`, MPS §15's three-tier model) — `fingerprint_for()` plus
    `RepositoryMemory`/`InMemoryRepositoryMemory` (tier 2: suppressions) and
    `GlobalKnowledge`/`StaticGlobalKnowledge` (tier 3: a small built-in CWE-summary catalog).
    100%-covered; a new "Agents do not depend on interface/delivery layers" import-linter contract
    (forbidding only `cli`/`server`/`sdk`, not peer adapters, since agents coordinate other
    packages the way the orchestrator does).
  - **Provider-agnostic `LLMPort` factory** (`cortexward.llm.provider_config`): per the
    architecture decision that CortexWard must never depend on a specific LLM provider,
    `build_llm(LLMProviderConfig) -> LLMPort` is now the *one* place in the codebase that branches
    on provider identity — every other component still depends on `LLMPort` alone. Three new
    reference adapters fill out MPS §14's provider list behind that one factory:
    **`OpenAICompatibleAdapter`** (one adapter, `base_url`-differentiated, covers OpenAI, Groq,
    OpenRouter, LM Studio, and self-hosted vLLM — all speak the same `/chat/completions` schema),
    **`AnthropicAdapter`** (`/v1/messages`; a top-level `system` field rather than a message role;
    `max_tokens` required, so a request that omits it gets a documented default; typed `content`
    blocks parsed into text/tool-use), and **`GeminiAdapter`** (`/models/{model}:generateContent`;
    API key as a query parameter; `user`/`model` roles and `contents[].parts`; `functionCall` args
    already parsed, unlike OpenAI's JSON-encoded-string arguments). None of the three is
    live-verified in this environment (no commercial API keys) — each is unit-tested against its
    provider's own published, stable REST schema instead (deterministic, no network), consistent
    with `OllamaAdapter` staying the only adapter genuinely exercised against a live server here.
    `cost_estimate` raises `NotImplementedError` on all three rather than returning `0.0`, since
    none has a maintained per-model price table and misrepresenting a paid API as free would be
    actively wrong. `load_llm_config()` (`cortexward.llm.config_loader`) reads one
    `LLMProviderConfig` from a YAML file (`provider`, `model`, optional
    `api_key`/`api_key_env`/`base_url`), so switching providers is a configuration change, never an
    application-code change — malformed config raises `LLMConfigError` with a clear reason rather
    than a bare `KeyError` from deep inside the loader. 100%-covered.
  - **The seven agents and `AgentOrchestrator`** (`cortexward.agents.orchestrator`), completing the
    `cortexward-agents` foundation above. `PlannerAgent` renders a run plan from the target root
    and languages. `ScannerAgent` runs every configured `ScannerPort` and correlates the results —
    the same step `SequentialOrchestrator` performs, as one `Agent`. `VerifierAgent` asks the model
    for a `VERDICT: REAL|FALSE_POSITIVE|UNCERTAIN - <reason>` per finding and attaches it as an
    `LLM_ASSESSMENT` `Evidence` via `finding.with_evidence(...)` + `apply_assessment(...)` —
    structurally this agent can never singlehandedly move a finding to `VERIFIED`: the domain's
    LLM-insufficiency policy caps LLM-only confidence below `VERIFIED_THRESHOLD` regardless of
    verdict. `RepairAgent` proposes a candidate `Patch` (parsed from a `DESCRIPTION:`/`DIFF:`
    response) for each `VERIFIED` finding only; an unparseable response is skipped, not
    fabricated. `ReviewerAgent` records an advisory APPROVE/REJECT/NEEDS_CHANGES verdict as a
    `RunState` note only — it deliberately never sets `Patch.tests_pass`/`rescan_clean`/
    `exploit_neutralized`, since an LLM opinion can't honestly stand in for the three-gate
    validation MPS §16 requires before `Patch.is_validated`. `MemoryAgent` dismisses findings
    matching a known `RepositoryMemory` suppression and persists newly `REFUTED` findings as new
    ones. `CoordinatorAgent` renders the final run summary. `AgentOrchestrator` implements
    `OrchestratorPort` by running a fixed `Agent` sequence over one `RunState` — the same drop-in
    `run(request) -> RunResult` contract `SequentialOrchestrator` satisfies; `default_agents()`
    assembles the standard seven-agent pipeline. 100%-covered with deterministic scripted-LLM unit
    tests (including verifying the exact confidence math that keeps LLM-only verification from
    reaching `VERIFIED`), plus a genuine end-to-end run against the real local Ollama server
    (`qwen2.5-coder:7b`) and a real `BanditScanner` finding — skipped when no local Ollama server
    is reachable, mirroring `OllamaAdapter`'s own `TestLiveOllama` pattern.
  - **`VerifierAgent` reachability evidence** — the first evidence this framework produces that
    isn't LLM judgement. `CodeGraph` (`cortexward.ports.code_graph`) gained `nodes_at(path, line)
    -> Sequence[NodeId]`, the reverse of `location_of`, implemented in `InMemoryCodeGraph`
    (`cortexward-cpg`) as an ordered-by-span-size scan over every node at that location.
    `build_code_graphs()` (`cortexward.agents.code_graphs`) auto-discovers registered
    `LanguageProvider`s exactly the way `default_scanners()` discovers scanners, parsing the
    target root once per run; a broken/unsupported language is skipped, not fatal to the others.
    `VerifierAgent` now checks *every* node a finding's location resolves to, not just the most
    specific one — empirically verified (not assumed) that the reference CFG builder only links
    `CFG_NEXT` edges between sibling statement nodes, so an inner call/expression node commonly
    isn't itself part of that chain even though a sibling statement node at the identical source
    span is; picking only the smallest-span node silently produced false negatives before this
    fix. A `REACHABILITY_PROOF` `Evidence` is attached only on a genuine positive proof — a
    finding whose location isn't provably reachable is left alone, never treated as refuted,
    since the entrypoint heuristic (`main()` / `if __name__ == "__main__":` guards only) is
    deliberately narrow and "not proven reachable by this heuristic" is not the same claim as
    "proven unreachable." 100%-covered; the live end-to-end Ollama test was updated to assert
    genuine `REACHABILITY_PROOF` evidence on a real Bandit finding — its vulnerable call now sits
    directly in an `if __name__ == "__main__":` guard after a helper-function-wrapped version was
    tried first and found provably unreachable with the current CFG builder (a real, documented
    limitation of the Phase 2 reference implementation, not a bug introduced here).
- **Phase 3.5 (in progress) — Evaluation harness.**
  - New workspace package `cortexward-eval`, depending on `cortexward-core`.
  - **`RunManifest`** (`cortexward.eval.manifest`): the immutable per-run provenance record
    (evaluation-framework.md §5) — git SHA, config hash, calibration profile, dataset ref, model
    refs (with training cutoff, for contamination-split classification), prompt versions,
    runtime/hardware, cost, and a `DetectionMetrics` block. Frozen, `extra="forbid"` pydantic
    models, mirroring the domain `Finding` aggregate's strictness.
  - **Deterministic finding-matcher & detection metrics** (`cortexward.eval.metrics`):
    `match_findings()` matches predicted `Finding`s against labeled `GroundTruthFinding`s by CWE
    compatibility + location overlap, via greedy bipartite matching in input order — documented
    and reproducible, not merely "close enough," since TP/FP/FN counts must be identical across
    repeated runs to be a valid research claim. `precision`/`recall`/`f1_score` plus
    `false_positive_rate`/`false_negative_rate` (redefined as `1 - precision`/`1 - recall`, since
    open-ended vulnerability detection has no fixed "negative" universe the classic
    `FP / (FP + TN)` formula assumes — documented explicitly rather than silently misapplying it).
  - A new "Evaluation harness does not depend on other adapters or interfaces" import-linter
    contract, expected to loosen once the harness's `ward bench run` invokes scanners/reporters
    directly.
  - **Statistical protocol** (`cortexward.eval.statistics`): `bootstrap_ci` — a general
    percentile-bootstrap confidence interval over any statistic of per-example values (seedable
    for reproducibility), the primitive "paired bootstrap CIs over per-example results" (§6)
    reduces to. `mcnemar_test` — the continuity-corrected chi-square test for matched binary
    "detected / not" outcomes, with an exact closed-form chi-square(1) CDF via `math.erf` rather
    than adding a `scipy` dependency for one special case (a chi-square(1) variable is the square
    of a standard normal).
  - 100%-covered.
- **Phase 3 (in progress) — Scanner adapters.**
  - New workspace package `cortexward-scanners`, depending on `cortexward-core`.
  - **Bandit adapter** (`cortexward.scanners.bandit_scanner.BanditScanner`): invokes
    `python -m bandit -f json` as a subprocess and maps its JSON results to `RawFinding` (rule id,
    message, `SourceLocation`, severity hint, CWE, and Bandit's native fields preserved in `raw`
    for audit). Bandit only parses Python's AST — it never executes analyzed code, so this doesn't
    touch the non-execution guarantee (ADR-0004), which is about the *analyzed project's* code.
    Registered under the `cortexward.scanners` entry-point group; excludes common non-source
    directories (`.venv`, `node_modules`, ...) and respects the `languages` filter.
  - 100%-covered tests running the real `bandit` package against fixture files (no subprocess
    mocking), plus direct tests of internal parsing helpers for JSON shapes Bandit's schema
    doesn't rule out but its current behavior doesn't produce.
  - **Secrets adapter** (`cortexward.scanners.secrets_scanner.SecretsScanner`): uses
    detect-secrets' native Python API directly (`SecretsCollection.scan_files`) — a pure-Python
    library, so no subprocess or external binary needed. Ignores the `languages` filter entirely:
    secrets aren't scoped to one grammar the way SAST rules are. Preserves detect-secrets' one-way
    `hashed_secret` in `RawFinding.raw`, never the plaintext, so a scan result can never itself
    become a new leak. Test fixtures build fake tokens by string concatenation rather than a
    single literal, so the test source itself never contains a contiguous, real-looking secret
    that this repo's own gitleaks self-audit (CI) would flag.
  - A new import-linter contract ("Scanner adapters do not depend on other adapters or
    interfaces") mirrors the existing CPG-engine contract for symmetry.
  - **Cross-tool normalization & correlation** (`cortexward.scanners.normalize`/`correlate`):
    `normalize()` turns one `RawFinding` into a `Finding` with one supporting `STATIC_MATCH`
    `Evidence` at `VerificationRung.NONE` ("only a raw detection signal exists," per the ladder's
    own definition of that rung). `correlate()` runs multiple scanners' results through
    `normalize()` and merges findings sharing a CWE at the same file+line into a single `Finding`
    with multiple `Evidence` entries (worst-case severity, every contributing producer tagged) —
    the same real bug reported by several tools becomes one finding, not several duplicates. CWE
    is the only cross-tool identity signal used (rule ids and messages differ per tool for the
    same bug class); a finding with no CWE never merges with anything.
  - **SARIF export** — new workspace package `cortexward-reporters`, depending on
    `cortexward-core`. `SarifReporter` (`cortexward.reporters.sarif.SarifReporter`) implements
    `ReporterPort`, rendering `Finding`s into a SARIF 2.1.0 document: one `run`, one `tool.driver`
    identifying CortexWard itself, one deduplicated `reportingDescriptor` per distinct `rule_id`,
    `Severity` mapped to SARIF's `error`/`warning`/`note` levels, and CWE plus contributing-
    producer tags carried in `properties`. An export format only (ADR-0003) — `Finding` stays the
    richer internal model SARIF's single-message `result` shape can't fully express. Registered
    under the `cortexward.reporters` entry-point group; a new "Reporters do not depend on other
    adapters or interfaces" import-linter contract mirrors the CPG/scanners ones.
  - **CortexWard-native JSON export** — `JsonReporter` (`cortexward.reporters.json_reporter.
    JsonReporter`, `format_id = "cortexward-json"`), the "future work" `SarifReporter`'s own
    module docstring flagged for the full evidence trail SARIF can't carry. Delegates to
    `Finding.model_dump(mode="json")` rather than a hand-maintained field mapping — `Finding`
    (and everything it nests: `Evidence`, `Provenance`, `SourceLocation`) is already a pydantic
    model, so every `Evidence` item (an LLM assessment's reasoning text, a reachability proof's
    summary, the verification rung, ...) survives intact instead of being narrowed to just
    `state`, and stays automatically in sync with the domain model as it evolves rather than
    silently drifting the way a hand-rolled mapping would. Registered under `cortexward.reporters`
    alongside `sarif`; selectable from `ward scan --format cortexward-json` (see the CLI entry
    above). 100%-covered, including tests confirming evidence that would be dropped by
    `SarifReporter` survives here.
  - **Dependency-vulnerability adapter** (`cortexward.scanners.osv_scanner.OsvScanner`): queries
    the public OSV.dev API for known vulnerabilities in *exactly-pinned* dependencies (`==X.Y.Z`
    in `requirements*.txt` or a PEP 621 `dependencies` entry). Range constraints are skipped, not
    guessed at, since resolving one to an actual installed version needs a lockfile this scanner
    doesn't have; querying OSV without an exact version would return every vulnerability ever
    recorded for a package, a poor-quality signal deliberately avoided. Does its own minimal pin
    extraction over `urllib` (stdlib, no new HTTP dependency) rather than depending on
    `cortexward-cpg`'s `parse_dependencies` — only name+exact-version is needed, and scanner
    adapters don't depend on other adapters. Unlike the other adapters, this one is deliberately
    network-dependent: a vulnerability database is supposed to reflect the current threat
    landscape, so freshness is the point, not a compromise on this project's offline-determinism
    bar (contrast the still-deferred Semgrep adapter, where changing *rules* over time would hurt
    reproducible benchmarking). Network failure degrades to no findings, never a crash. Tests run
    real queries against OSV.dev's stable public API.
- **Phase 2 — Code Property Graph engine.**
  - New workspace package `cortexward-cpg`, depending on `cortexward-core`.
  - `cortexward.cpg.model`: the language-agnostic node/edge schema (`NodeKind`, `EdgeKind`,
    `Node`, `Edge`) unifying AST, control-flow, data-flow, and call edges.
  - `cortexward.cpg.graph`: `GraphBuilder` and `InMemoryCodeGraph`, the reference implementation
    of the `CodeGraph` port — cycle-safe `reachable`/`taint`/`callers`/`slice`/`location_of`,
    complete and correct over whatever edges exist even before CFG/DFG/call-graph builders land.
    Also exposes read-only `nodes`/`edges` accessors for downstream builders.
  - **Python `LanguageProvider`** (`cortexward.languages.python`): a tree-sitter AST walker
    producing the CPG's AST layer, `detect`/`dependency_manifests`/`parse`, registered under the
    `cortexward.languages` entry-point group. Entry points are marked heuristically (`main()`
    functions, `if __name__ == "__main__":` guards).
  - **Control-flow builder** (`_cfg_builder.py`): populates `CFG_NEXT` over the AST layer —
    sequential flow, `if`/`elif`/`else`, `while`/`for` (incl. `break`/`continue`/loop-`else`),
    `with`, and `return`, with each function/class body as an independent scope.
    `try`/`except`/`finally` is intentionally out of scope (documented, not silently missing).
    Required switching the AST↔CFG node-identity key from Python object `id()` to
    `(start_byte, end_byte, type)` after discovering tree-sitter's `Node` wrapper objects are
    not stable across separate tree traversals.
  - **Data-flow builder** (`_dfg_builder.py`): a classic iterative reaching-definitions analysis
    (`IN[n] = ∪ OUT[pred]`, `OUT[n] = GEN[n] | (IN[n] - KILL[n])`) over the CFG_NEXT edges above,
    populating `DFG_REACHES` for plain/augmented assignment, `for`-loop targets, and function
    parameters as definitions, and any variable reference (excluding attribute/keyword-argument
    names) as a use — the def-use foundation real taint analysis (ladder rung 2) needs. Function
    parameters seed a body's entry set directly (`entry_seeds`), since a function's own `def`
    statement has no `CFG_NEXT` edge into its body (a function is entered by a call, not by
    falling through).
  - **Call-graph builder** (`_call_graph_builder.py`): best-effort, same-file, name-based
    resolution populating `CALLS` — bare-identifier calls (`foo()`) resolve against plain
    function definitions, attribute calls (`self.method()`) resolve against method definitions,
    each collected in one pass over the tree before calls are resolved in a second pass (so
    forward references to a not-yet-seen definition still resolve). Deliberately
    over-approximates ambiguous same-named matches — every match gets its own edge — rather than
    risk missing a real one; this enables `CodeGraph.callers()` and multi-function reachability
    through `CALLS`. Cross-file and type-aware resolution are explicitly out of scope (future
    dependency-graph work).
  - **Dependency-manifest parsing** (`_manifest_parser.py`, exported as `cortexward.languages.
    python.parse_dependencies`): reads (never executes) `pyproject.toml` (PEP 621),
    `requirements*.txt`, `setup.cfg`, and `Pipfile` into structured `Dependency` records (name,
    version constraint, source manifest, runtime/dev/optional kind). `setup.py` is explicitly out
    of scope (extracting `install_requires` reliably needs execution, forbidden by ADR-0004).
    Returns plain data rather than `CodeGraph` nodes — the MPS's "dependency graph" layer's exact
    shape isn't pinned down yet, and this is exactly what a future dependency-scanning adapter
    needs without forcing that decision early. **Phase 2 is now complete.**
  - 100%-covered tests including cycle, diamond-revisit, self-sink, unreadable-path, and
    malformed-tree-defense cases.
- **Test infrastructure fix:** adopted pytest's `--import-mode=importlib` and dropped
  `__init__.py` from every package's `tests/` tree, after adding a second workspace package
  revealed a real collision (`tests` as a shared top-level module name). `mypy` now runs once per
  package for the same reason. Test builders (`make_evidence`, `make_finding`) moved from
  importable helpers to pytest fixtures.
- **Phase 1.5 — Workspace & contracts.**
  - Restructured into a **uv workspace monorepo**: `packages/cortexward-core/` is the first
    independently versioned package; `cortexward` is now a PEP 420 namespace package so future
    packages (`cortexward-cpg`, `cortexward-llm`, ...) can each contribute a subpackage without
    conflict (`ADR-0005`). Package version moves to `cortexward.core.version()`.
  - The full **port catalog** (`cortexward.ports`) as `typing.Protocol` contracts:
    `LanguageProvider`, `CodeGraph`, `ScannerPort`, `LLMPort`/`EmbeddingPort`, `SandboxPort`,
    `VCSPort`, `StoragePort`, `TelemetryPort`, `OrchestratorPort`, `ReporterPort` — each with a
    conformance test.
  - The **plugin registry** (`cortexward.plugins`): entry-point-based discovery and lazy loading
    of adapters, with zero core changes required to add a new plugin.
  - **import-linter** contracts mechanically enforcing the hexagonal dependency direction.
  - CI hardened for the workspace: `uv sync --all-packages`, a 100% coverage gate, an
    import-boundary check, a dogfood Bandit scan, and a CycloneDX SBOM artifact.
- **Master Project Specification v1.0** (`docs/specifications/MPS-v1.0.md`) — the single source of
  truth (RFC): vision, requirements, system/component/agent architecture, domain model, CPG spec,
  LLM abstraction + routing, prompt/memory architecture, patch pipeline, plugin/port catalog,
  event & data flow, database design, API contracts, integrations, security architecture & threat
  model, benchmark/evaluation, performance & scalability, repo structure, standards, release &
  versioning, governance, and a reordered roadmap.
- **Evaluation Framework** (`docs/benchmark/evaluation-framework.md`) — benchmark-first metrics,
  contamination-controlled datasets, `RunManifest`, statistical protocol, and harness contract.
- **Phase-1 technical review** (`docs/reviews/`) challenging the initial decisions.
- **ADR process and records 0000–0008** (`docs/adr/`) freezing the architecture post-approval,
  including the uv-workspace restructure, owned LLM abstraction, benchmark-first ordering, and
  event-sourced findings.
- Roadmap reordered to benchmark-first with new **Phase 1.5** (workspace + contracts + CI
  hardening) and **Phase 3.5** (evaluation harness).
- **Phase 0 — Research & architecture.** Critical analysis of the research brief; adoption of
  the Verification Ladder and VEX/SARIF/SBOM outputs; hexagonal, in-process architecture.
  Design captured in `ARCHITECTURE.md`, `ROADMAP.md`, and `research/`.
- **Phase 1 — Foundation.**
  - `cortexward` package with a pure, framework-free domain core: `Finding`, `Evidence`,
    `Provenance`, `SourceLocation`, `Patch`, and the `Assessment` value object.
  - The Verification Ladder calibration engine (`calibrate_confidence`, `assess`,
    `apply_assessment`) with log-odds evidence combination, the "LLM is never sufficient"
    policy, and refutation as first-class evidence.
  - Tooling: `uv`, Ruff (lint + format), `mypy --strict`, `pytest` + `hypothesis`; domain core
    at 100% coverage.
  - CI: lint · format · type · test matrix (Python 3.11–3.13) plus a self-audit job
    (`gitleaks`, `pip-audit`).
  - Open-source governance: `README`, `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`,
    `GOVERNANCE`, issue/PR templates, `Dockerfile`, and a devcontainer.

[Unreleased]: https://github.com/amarjaleelbanbhan/CortexWard/commits/main
