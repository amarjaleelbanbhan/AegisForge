# Changelog

All notable changes to CortexWard are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **Project renamed from AegisForge to CortexWard.** AegisForge collided with dozens of existing
  GitHub projects, several directly in the same space; CortexWard is confirmed clean across
  GitHub, PyPI, and npm. GitHub repo renamed (About description + topics set); packages renamed
  to `cortexward-{core,cpg}`; the Python namespace moved from `aegisforge.*` to `cortexward.*`
  throughout; the derived CLI shorthand `aegis` → `ward`. No functional changes.

### Added
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
