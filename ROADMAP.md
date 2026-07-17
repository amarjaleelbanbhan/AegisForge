# CortexWard Roadmap

> **Authoritative ordering:** [MPS §29](docs/specifications/MPS-v1.0.md#29-roadmap). The MPS
> reorders the roadmap to be **benchmark-first** ([ADR-0007](docs/adr/0007-benchmark-first.md)),
> inserting **Phase 1.5** (workspace migration + port contracts + CI hardening) and **Phase 3.5**
> (evaluation harness) ahead of the heavy agent work. This page is the readable summary; the MPS
> table governs.

CortexWard is built in strict, shippable phases. Each phase completes a coherent capability
with tests, documentation, and a green CI before the next begins. Phases are capability-based,
not calendar-based: the goal is a system that is always in a releasable state.

Legend: ✅ done · 🚧 in progress · ⏳ planned

---

## Phase 0 — Research & architecture ✅
Analyze the research brief, strengthen the thesis (Verification Ladder + VEX), choose the
architecture (hexagonal, in-process orchestration), and record the roadmap.
- Deliverables: [ARCHITECTURE.md](ARCHITECTURE.md), this roadmap, [`research/`](research/).

## Phase 1 — Foundation ✅
Repository, tooling, CI, and the pure domain core.
- ✅ `cortexward` package, `uv`/Ruff/mypy-strict/pytest, `pyproject.toml`.
- ✅ Domain core: `Finding`, `Evidence`, Verification Ladder, `Patch`, `Provenance`,
  `Assessment` — 100% covered, property-tested.
- ✅ CI (lint · format · type · test matrix) + self-audit (secrets, deps).
- ✅ Governance docs, issue/PR templates, Dockerfile, devcontainer.

## Phase 1.5 — Workspace & contracts ✅ *(from the MPS review)*
Restructured before the codebase ossified.
- ✅ uv workspace monorepo + `cortexward.*` namespace package
  ([ADR-0005](docs/adr/0005-uv-workspace-monorepo.md)); `cortexward-core` is the first member.
- ✅ Full port catalog as `typing.Protocol` contracts (`cortexward.ports`) with conformance
  tests, and the entry-point plugin registry (`cortexward.plugins`).
- ✅ `import-linter` contracts mechanically enforcing the hexagonal dependency direction.
- ✅ CI hardened for the workspace: `uv.lock` committed, 100% coverage gate, a dogfood security
  scan, and a CycloneDX SBOM artifact. *(Signed release provenance is deferred to Phase 10,
  where release automation is specified — MPS §27.)*

## Phase 2 — Code intelligence ✅
Language-agnostic Code Property Graph on tree-sitter (AST → CFG → DFG → call graph), a query
API, and dependency-manifest parsing. Python first.
- Enables reachability + taint (ladder rungs 1–2) and grounded LLM retrieval.
- ✅ **Graph engine** (`cortexward-cpg`): the node/edge schema (`cortexward.cpg.model`) and the
  reference in-memory `CodeGraph` implementation (`cortexward.cpg.graph`) — `GraphBuilder` plus
  cycle-safe `reachable`/`taint`/`callers`/`slice`/`location_of` queries. Complete and correct
  over whatever edges exist; a graph built from AST alone honestly reports no control/data paths
  until the builders below populate more edges.
- ✅ **Python `LanguageProvider`** (`cortexward.languages.python`): tree-sitter AST parsing into
  the schema above — `detect`/`dependency_manifests`/`parse`, registered under the
  `cortexward.languages` entry-point group. Entry points are marked heuristically (`main()`
  functions and `if __name__ == "__main__":` guards); framework-specific route/handler detection
  is future work.
- ✅ **Control-flow graph builder** (`cortexward.languages.python._cfg_builder`): populates
  `CFG_NEXT` over the AST layer — sequential flow, `if`/`elif`/`else`, `while`/`for` (incl.
  `break`/`continue`/loop-`else`), `with`, and `return`, with each function/class body as an
  independent scope. `try`/`except`/`finally` is explicitly out of scope (a `try_statement` is
  atomic here); exception control flow is its own future builder.
- ✅ **Data-flow graph builder** (`cortexward.languages.python._dfg_builder`): iterative
  reaching-definitions dataflow analysis over the CFG, populating `DFG_REACHES` from each
  definition (plain/augmented assignment, `for`-loop targets, function parameters) to every use
  it reaches — the foundation for real taint analysis (ladder rung 2).
- ✅ **Call graph builder** (`cortexward.languages.python._call_graph_builder`): best-effort,
  same-file, name-based resolution populating `CALLS` from each call site to the function/method
  definition(s) it matches (bare-identifier calls against plain functions, attribute calls
  against methods), enabling `CodeGraph.callers()` and multi-function reachability. Deliberately
  over-approximates on ambiguous names rather than risk missing a real edge; cross-file and
  type-aware resolution are future work.
- ✅ **Dependency-manifest parsing** (`cortexward.languages.python.parse_dependencies`): reads
  (never executes) `pyproject.toml` (PEP 621), `requirements*.txt`, `setup.cfg`, and `Pipfile`
  into structured `Dependency` records (name, version constraint, manifest, runtime/dev/optional).
  `setup.py` is explicitly out of scope — extracting its dependencies reliably requires executing
  it, which the non-execution guarantee (ADR-0004) forbids. Returns plain data rather than
  `CodeGraph` nodes/edges for now — the MPS's "dependency graph" layer's exact shape (one node
  per package? per manifest?) isn't pinned down yet, and this is exactly what a future
  dependency-scanning adapter (Phase 3) needs without forcing that decision early.

## Phase 3 — Scanners 🚧
Adapters for Semgrep, Bandit, secret scanning, and dependency scanning, normalized to the
`Finding` schema, with cross-tool dedup/correlation and SARIF export.
- ✅ **Bandit adapter** (`cortexward-scanners`, new workspace package): `BanditScanner`
  implements `ScannerPort` by invoking `python -m bandit -f json` as a subprocess (never executes
  analyzed code — Bandit itself only parses Python's AST) and mapping its JSON results to
  `RawFinding` (rule id, message, location, severity hint, CWE, native fields preserved in `raw`).
  Registered under the `cortexward.scanners` entry-point group.
- ✅ **Secrets adapter**: `SecretsScanner` implements `ScannerPort` via detect-secrets' native
  Python API (`SecretsCollection.scan_files` — no subprocess, no external binary). Language-
  agnostic by design (ignores the `languages` filter — a leaked credential in a `.env` file is as
  real as one in a `.py` file); preserves detect-secrets' one-way `hashed_secret`, never the
  plaintext, so a scan result can never itself become a new leak.
- ✅ **Cross-tool normalization & correlation** (`cortexward.scanners.normalize`/`correlate`):
  turns any scanner's `RawFinding`s into the domain `Finding` aggregate — one supporting
  `STATIC_MATCH` `Evidence` at `VerificationRung.NONE`, exactly what "only a raw detection signal
  exists" means on the ladder. `correlate()` merges findings from *different* scanners that share
  a CWE at the same file+line into a single `Finding` with multiple `Evidence` entries (worst-case
  severity, every contributing producer tagged) — one real bug reported by several tools becomes
  one finding, not several duplicates. A finding with no CWE never merges with anything; CWE is
  the only tool-agnostic identity signal used, deliberately not rule-name or message similarity.
- ✅ **SARIF export** (`cortexward-reporters`, new workspace package): `SarifReporter` implements
  `ReporterPort`, rendering `Finding`s into a SARIF 2.1.0 document — one `run`, one `tool.driver`
  (CortexWard itself), one deduplicated `reportingDescriptor` per distinct `rule_id`, severity
  mapped to SARIF's `error`/`warning`/`note` levels, CWE and contributing-producer tags carried in
  `properties`. An export format only (ADR-0003) — `Finding` stays the richer internal model
  (evidence, verification rung, VEX status) that SARIF's single-message `result` shape can't
  express.
- ✅ **CortexWard-native JSON export**: `JsonReporter` (`cortexward.reporters.json_reporter`,
  `format_id = "cortexward-json"`), the "future work" `SarifReporter`'s own docstring flagged for
  the full evidence trail SARIF can't carry. Delegates to `Finding.model_dump(mode="json")` rather
  than a hand-maintained field mapping, since `Finding`/`Evidence`/`Provenance` are already
  pydantic models — every `Evidence` item (LLM assessment reasoning, reachability-proof summaries,
  verification rung, ...) survives intact instead of being narrowed to just `state`. Registered
  under `cortexward.reporters` alongside `sarif`; selectable from `ward scan --format
  cortexward-json` (see Phase 8).
- ✅ **Dependency-vulnerability adapter**: `OsvScanner` queries the public OSV.dev API for known
  vulnerabilities in *exactly-pinned* dependencies (`==X.Y.Z` in `requirements*.txt` or a PEP 621
  `dependencies` entry). Range constraints (`>=2.0`) are skipped, not guessed at — resolving a
  range to "the version actually in use" needs a lockfile or an installed environment, which a
  bare `root: Path` doesn't give us; querying OSV without an exact version returns every
  vulnerability ever recorded for that package, a poor-quality signal this scanner deliberately
  avoids producing. Does its own minimal pin-extraction (not `cortexward-cpg`'s
  `parse_dependencies`) to respect the "scanners don't depend on other adapters" boundary — only
  name+exact-version is needed, not the full `Dependency` record. Unlike the other adapters, this
  one is deliberately network-dependent: a vulnerability database is supposed to reflect the
  current threat landscape, so freshness is the point here, not a compromise (contrast the
  Semgrep deferral below, where changing rules over time would hurt reproducible benchmarking).
  Network failure degrades to no findings, never a crash.
- ⏳ Semgrep adapter (needs an offline, non-registry rule pack — `--config=auto` requires
  network access to semgrep.dev, which conflicts with this project's offline-determinism bar).

## Phase 3.5 — Evaluation harness 🚧 *(benchmark-first)*
Built before advanced agents so every later feature is measured
([ADR-0007](docs/adr/0007-benchmark-first.md), [Evaluation Framework](docs/benchmark/evaluation-framework.md)).
- ✅ **`RunManifest`** (`cortexward-eval`, new workspace package): the immutable per-run
  provenance record from evaluation-framework.md §5 — git SHA, config hash, calibration profile,
  dataset ref, model refs (with training cutoff, for the contamination split), prompt versions,
  runtime/hardware, cost, and the metrics block. Frozen, strict pydantic models — the same
  audit-critical strictness as the domain `Finding` aggregate.
- ✅ **Deterministic finding-matcher & detection metrics** (`cortexward.eval.metrics`): matches
  predicted `Finding`s against labeled `GroundTruthFinding`s by CWE compatibility + location
  overlap (same file, overlapping line range), via greedy bipartite matching in input order — a
  documented, reproducible matcher, not an approximate one, since TP/FP/FN counts must be
  identical across repeated runs of the same inputs to be a meaningful research claim. Computes
  precision/recall/F1, plus FPR/FNR redefined as `1 - precision`/`1 - recall` (there's no fixed
  "negative" universe in open-ended vulnerability detection, unlike classifying a fixed labeled
  set — documented explicitly rather than silently reusing the classic binary-classification
  formula where it wouldn't apply).
- ✅ **Statistical protocol** (`cortexward.eval.statistics`): `bootstrap_ci` — a general
  percentile-bootstrap confidence interval for any statistic over per-example values (paired
  detection-delta CIs are the `statistic=mean` case over per-example differences, per §6, but the
  function itself is metric-agnostic since the dataset's negative-example shape isn't decided
  yet). `mcnemar_test` — the continuity-corrected chi-square test for matched binary "detected /
  not" outcomes between two configurations, using an exact closed-form chi-square(1) CDF
  (`math.erf`) rather than adding a `scipy` dependency for one special case.
- ⏳ A versioned **golden dataset** with contamination controls (memorized/post-cutoff/mutated/
  novel splits) and the `ward bench run/compare/report` harness contract itself — these need the
  dataset-sourcing and CLI-surface decisions the MPS defers to this phase, not yet made.

## Phase 4 — Agent framework 🚧
Orchestrator (behind `OrchestratorPort`; LangGraph adapter) and agents (Planner, Scanner,
Verifier, Repair, Reviewer, Coordinator, Memory), an `LLMPort` with pluggable backends, and a
cost-aware model router.
- ✅ **`cortexward-llm`** (new workspace package): the owned LLM abstraction (MPS §14, ADR-0006).
  - **`OllamaAdapter`** implements `LLMPort` against a local Ollama server's `/api/chat` — needs no
    API key (Ollama runs entirely on-device), and is the only one of the MPS's six required v1
    adapters (Anthropic, OpenAI, Gemini, Ollama, OpenAI-compatible, LiteLLM) buildable and
    genuinely integration-testable without provider credentials this environment doesn't have.
    `cost_estimate` is always `0.0` (no per-token billing for local inference); `count_tokens` is
    a documented ~4-chars-per-token heuristic (Ollama exposes no standalone tokenizer endpoint).
    100%-covered via monkeypatched request/response-mapping tests (deterministic, always run) plus
    a small `TestLiveOllama` class that talks to a real local server when one is reachable and
    skips otherwise — this project's CI has no Ollama installed, unlike OSV.dev's public API.
  - **`ModelRouter`**: the declarative task-class → model-tier → adapter router from MPS §14
    (`TRIAGE`/`REASONING`/`PATCH_GENERATION` → `CHEAP`/`STRONG`), config-driven and overridable per
    run (`tier_overrides`), with `offline=True` pinning every task class to the local tier. Fully
    unit-tested against fake `LLMPort` adapters — no network dependency at all.
  - Registered under the `cortexward.llm` entry-point group; a new "LLM adapters do not depend on
    other adapters or interfaces" import-linter contract mirrors the existing adapter-family ones.
- ✅ **`cortexward-orchestrator`** (new workspace package): `SequentialOrchestrator` implements
  `OrchestratorPort` — runs every configured `ScannerPort` in sequence, then normalizes and
  correlates the results into `Finding`s via `cortexward.scanners.correlate`. No LLM or agent
  reasoning yet; this is the reference in-process orchestrator that "run every scanner and merge
  the results" needs before any agent-driven planning/verification/repair. `default_scanners()`
  auto-discovers every scanner registered under the `cortexward.scanners` entry-point group, so a
  full scan → correlate → SARIF pipeline runs end to end with zero hardcoded scanner list. Unlike
  its peer adapter packages, the orchestrator is deliberately *not* isolated from
  `cortexward.scanners` — coordinating other adapters is its whole job — but a narrower contract
  ("does not depend on interface/delivery layers") still keeps it from reaching into the
  not-yet-built CLI/server/SDK. 100%-covered: fake-scanner unit tests plus a real end-to-end run
  with `BanditScanner`/`SecretsScanner` against a fixture with a known vulnerability and secret.
- ✅ **`cortexward-agents`** (new workspace package): the agent-framework foundation — `RunState`
  (stateless functions over shared, typed state per MPS §13), the `Agent` protocol, `ResilientLLM`
  (retry + cross-adapter fallback), `run_tool_loop` (bounded tool-calling round trip), `load_prompt`
  (versioned, hashed, package-bundled templates for all five v1 agent prompts), and the MPS §15
  memory abstractions (`RepositoryMemory`/`GlobalKnowledge`). 100%-covered.
- ✅ **Multi-provider `LLMPort`**: per the architecture decision that CortexWard must never depend
  on a specific LLM provider, `build_llm(LLMProviderConfig)` (`cortexward.llm.provider_config`) is
  now the one place that branches on provider identity. `OpenAICompatibleAdapter` (OpenAI, Groq,
  OpenRouter, LM Studio, vLLM — one `/chat/completions`-shaped adapter differentiated by
  `base_url`), `AnthropicAdapter` (`/v1/messages`), and `GeminiAdapter`
  (`/models/{model}:generateContent`) fill out the remaining five of MPS §14's six required v1
  adapters behind `LLMPort`, unit-tested against each provider's documented REST schema
  (deterministic, no network — none is live-verified in this environment, unlike `OllamaAdapter`).
  `load_llm_config()` reads a `provider`/`model`/`api_key(_env)`/`base_url` YAML file, so switching
  providers is a configuration change only. 100%-covered.
- ✅ **The seven agents and `AgentOrchestrator`**, built on the `cortexward-agents` foundation
  above: `PlannerAgent` (renders a run plan), `ScannerAgent` (runs configured `ScannerPort`s and
  correlates), `VerifierAgent` (LLM verdict → `LLM_ASSESSMENT` `Evidence` → `apply_assessment`;
  structurally can never singlehandedly reach `VERIFIED` — the domain's LLM-insufficiency policy
  caps LLM-only confidence below `VERIFIED_THRESHOLD`), `RepairAgent` (verified finding → candidate
  `Patch`, parsed from a `DESCRIPTION:`/`DIFF:` response), `ReviewerAgent` (advisory
  APPROVE/REJECT/NEEDS_CHANGES verdict recorded as a run note only — it never sets a `Patch` gate
  field, since an LLM opinion can't honestly stand in for the three-gate validation MPS §16
  requires), `MemoryAgent` (dismisses findings matching a known suppression, persists newly
  refuted findings as new ones), and `CoordinatorAgent` (final run summary). `AgentOrchestrator`
  implements `OrchestratorPort` by running a fixed `Agent` sequence over one `RunState`, the same
  drop-in contract `SequentialOrchestrator` satisfies; `default_agents()` assembles the standard
  seven-agent pipeline. 100%-covered with deterministic scripted-LLM unit tests, plus a genuine
  end-to-end run against the real local Ollama server (`qwen2.5-coder:7b`) and a real
  `BanditScanner` finding — skipped when no local Ollama server is reachable, mirroring
  `OllamaAdapter`'s own `TestLiveOllama` pattern.
- ✅ **`VerifierAgent` reachability evidence** — the first non-LLM evidence this framework
  produces. `CodeGraph` (MPS §12/§17.1) gained a `nodes_at(path, line) -> Sequence[NodeId]` method
  (implemented in `InMemoryCodeGraph`, reference-counted from smallest span to largest), the
  reverse of `location_of`, resolving a scanner-reported finding location back to graph nodes.
  `build_code_graphs()` (`cortexward.agents.code_graphs`) auto-discovers registered
  `LanguageProvider`s the same way `default_scanners()` discovers scanners, parses the target
  root once per run, and tolerates a broken/unsupported language without aborting the others.
  `VerifierAgent` checks every node a finding's location resolves to (not just the most specific
  one — verified empirically that the reference CFG builder only links CFG_NEXT edges between
  sibling statement nodes, so an inner call/expression node commonly isn't itself part of that
  chain even though a sibling statement node at the identical span is) and attaches a
  `REACHABILITY_PROOF` `Evidence` only on a genuine positive proof — a finding whose location
  isn't provably reachable is left alone, never treated as refuted, since the entrypoint heuristic
  (`main()` / `if __name__ == "__main__":` guards only) is deliberately narrow and "not proven
  reachable" is not the same claim as "proven unreachable." On its own this evidence is enough to
  raise a finding to `TRIAGED`; combined with a supporting LLM verdict it still falls short of
  `VERIFIED_THRESHOLD` — reaching `VERIFIED` needs taint/PoC/differential-test evidence this v1
  framework doesn't produce yet. 100%-covered; the live end-to-end Ollama test now asserts genuine
  `REACHABILITY_PROOF` evidence on a real Bandit finding whose vulnerable call sits directly in an
  `if __name__ == "__main__":` guard (a helper-function-wrapped call was tried first and found
  provably unreachable with the current CFG builder — documented in the test itself, not silently
  worked around).

## Phase 5 — Threat & architecture reasoning 🚧
STRIDE threat modeling, trust boundaries, attack-surface mapping, and business-logic analysis
grounded on the CPG.
- ✅ **STRIDE threat modeling**, grounded on existing scanner findings rather than a new detection
  capability: `Threat`/`ThreatModel` (`cortexward.domain.threat_model`) reclassify a `Finding`
  under Microsoft's STRIDE taxonomy via `stride_categories_for(cwe)`, a CWE→STRIDE lookup table
  covering every CWE this project's own scanners (Bandit's ~23 producible CWEs, detect-secrets'
  798) can actually produce, plus a handful of CWEs common in real-world CVEs an OSV-sourced
  finding could carry. STRIDE and CWE are orthogonal, uncanonical classification schemes — a CWE
  absent from the table yields an empty category set rather than a guessed one, mirroring
  `StaticGlobalKnowledge.cwe_summary()`'s "no entry means no claim" convention. A finding with no
  resolvable STRIDE category contributes no `Threat` at all.
  - **Attack-surface mapping**: `Threat.reachable_from_entrypoint` reuses the exact control-flow
    reachability query `VerifierAgent`'s `REACHABILITY_PROOF` evidence already performs — is this
    finding's location reachable from a known entry point? That query was extracted into
    `cortexward.agents.reachability.is_reachable_from_entrypoint()` so both consumers share one
    implementation instead of duplicating it; `VerifierAgent` now delegates to it, with no
    behavior change (its full test suite passes unmodified). Same one-directional honesty as
    everywhere else in this framework: `False` means "not proven reachable by this run's
    heuristics," never "proven unreachable."
  - **`build_threat_model()`** (`cortexward.agents.threat_model`) is deliberately not an `Agent`:
    STRIDE classification and reachability are both deterministic, so it needs no LLM and stays
    usable from a plain scanner pipeline, the same way `cortexward.cli.baseline` does.
  - **`build_threat_model_for()`** (`cortexward.orchestrator.threat_model`) mirrors
    `build_pipeline`'s role: scans a root, optionally builds a `CodeGraph`, and classifies the
    result — the one place `cortexward-orchestrator` depends on `cortexward.agents.threat_model`,
    keeping the CLI decoupled from `cortexward-agents` directly (the same separation
    `build_pipeline` already established).
  - **`ward threat-model <path>`** wires it into the CLI: JSON to stdout or `--output FILE`,
    `--language` filtering, `--reachability/--no-reachability`. No LLM flags, matching `ward
    baseline`'s design.
  - 100%-covered throughout, including real end-to-end tests: a genuine command-injection fixture
    scanned by the real `BanditScanner`, with a real CPG proving reachability from an
    `if __name__ == "__main__":` guard — no mocked scanner or graph.
- ⏳ Trust-boundary modeling (an explicit representation of the untrusted/trusted-control-plane
  split MPS §22.1 describes for CortexWard's own architecture, generalized to an analyzed
  target's architecture) and business-logic analysis remain unbuilt — both need design work this
  session didn't attempt, not just implementation.

## Phase 6 — Exploit verification ⏳
Sandbox (Docker → gVisor/Firecracker), the full ladder end to end, false-positive reduction,
PoC artifacts, and VEX output.

## Phase 7 — Patch generation 🚧
Minimal-diff automated repair with the three-gate validation (tests pass · rescan clean ·
exploit neutralized) and regression prevention.
- ✅ **`RepairAgent`/`ReviewerAgent`** (`cortexward-agents`, described under Phase 4 above) already
  cover minimal-diff generation and an advisory review; this phase's remaining piece was the
  **gate verification** MPS §16 requires before `Patch.is_validated`.
- ✅ **Gates A ("applies cleanly") and C ("rescan clean")** — `apply_and_rescan()`
  (`cortexward.agents.patch_gates`), wired into `ReviewerAgent` when `scanners` is given (as
  `default_agents()` does). Copies only the files a `Patch` touches into a scratch directory,
  applies the diff via `git apply` (a trusted external tool, never the analyzed project's own
  code — ADR-0004 stays intact), and re-runs the same scanners against the patched copy to check
  whether the original finding's `rule_id` still appears. Sets `Patch.rescan_clean` only on a
  genuine positive/negative result; an inconclusive outcome (patch didn't apply, referenced files
  missing, `git` unavailable) leaves it untouched rather than guessing. The diff comes from an
  LLM, treated as untrusted input: `Patch.files_changed` entries are validated against path
  traversal and absolute/drive-letter paths (checked with OS-independent string logic, not
  `pathlib.is_absolute()`, which is itself platform-dependent) before anything is read from the
  real project root or written to the scratch directory. `RunState` gained
  `with_patches_updated()` (replace semantics, unlike the existing append-only `with_patches()`)
  so Reviewer can record gate results on the patches Repair already proposed this run, not append
  duplicates. 100%-covered using the real `git` binary and the real `BanditScanner` — no mocking,
  since this module's entire job is applying a real diff and re-running a real scanner.
- ⏳ **Gates B ("existing tests pass") and D ("original PoC neutralized")** — both need to execute
  the analyzed project's own code (running its test suite, replaying a PoC), which needs Phase
  6's `SandboxPort` and doesn't exist yet. `Patch.is_validated` requires all three of
  `tests_pass`/`rescan_clean`/`exploit_neutralized` truthy, so a patch can reach `rescan_clean =
  True` through this work and still correctly have `is_validated = False` until Phase 6 lands —
  this is intentional, not a gap being hidden.

## Phase 8 — Delivery surfaces 🚧
CLI (Typer), REST API (FastAPI), GitHub App / Action, and a VS Code extension.
- ✅ **`cortexward-cli`** (new workspace package, pulled forward from strict phase order): the
  `ward` CLI, shipped early to close out `ci.yml`'s own long-standing dogfood-job note ("this job
  is replaced once cortexward-scanners exists, at which point `ward scan .` runs here") now that
  scanners and the orchestrator both exist. `ward scan <path>` wires `default_scanners()` →
  `SequentialOrchestrator` → `SarifReporter` into a runnable tool: SARIF to stdout or `--output
  FILE`, `--language` filtering, `--fail-on {none,low,medium,high,critical}` controlling the exit
  code (default `high`). **Now wired into `ci.yml`**: the dogfood job runs `ward scan` (bandit +
  detect-secrets + OSV, via `--baseline cortexward-baseline.json`) instead of standalone bandit,
  looped once per `packages/*/src` — the same scope the old bandit-only step used. The baseline
  is currently empty: this repo's only known false positives (fake secrets, `shell=True` examples)
  live in test fixtures, out of scope for a `src`-only scan, so nothing needs suppressing today.
  100%-covered via `typer.testing.CliRunner`, including real `BanditScanner`/
  `SecretsScanner` runs against fixtures (no mocking).
  - ✅ **`ward scan --llm-provider`** opts into the agent-driven pipeline
    (`cortexward.agents.AgentOrchestrator`) instead of `SequentialOrchestrator`, so findings carry
    real LLM verification and control-flow-reachability evidence rather than just raw scanner
    output — `--llm-provider`/`--llm-model`/`--llm-api-key(-env)`/`--llm-base-url` for a quick
    provider setup, or `--llm-config <yaml>` (reusing `cortexward.llm.load_llm_config`) for the
    full config-file path; `--no-reachability` opts out of the `build_code_graphs()` step. With no
    LLM flags given, behavior is byte-for-byte identical to before this — the agent pipeline is
    opt-in, never a silent default. 100%-covered, including a genuine end-to-end CLI invocation
    against the real local Ollama server — skipped when none is reachable.
  - ✅ **`ward scan --format`** selects the `ReporterPort` to render via the plugin registry
    (`registry_for(PluginGroup.REPORTERS)`, the same discovery pattern `default_scanners()` uses)
    instead of a hardcoded `SarifReporter()` — `sarif` (default) or `cortexward-json`, and any
    future reporter is selectable with zero CLI code changes. This closes the gap the
    `--llm-provider` bullet above left open: SARIF's `properties.state` reflects the richer
    verification outcome, but the underlying evidence list needs `--format cortexward-json` to
    actually be visible. 100%-covered, including an unknown-format rejection test.
  - ✅ **`ward scan --baseline`** and **`ward baseline`** — a findings baseline/suppression
    mechanism (`cortexward.cli.baseline`), closing the gap the bullet above left open: known/
    accepted findings a scan shouldn't re-flag. `ward baseline <path> [--output FILE] [--reason
    TEXT]` runs the plain scanner pipeline (deliberately no LLM — a baseline records what the
    scanners themselves find today, not an LLM-influenced verification outcome) and writes each
    finding's fingerprint to a JSON file (`{"suppressions": [{"fingerprint", "rule_id", "path",
    "reason"}]}`); `ward scan --baseline FILE` excludes any finding whose fingerprint is listed
    from both the rendered report and the `--fail-on` exit-code check. The identity primitive,
    `fingerprint_for()` (stable hash of `rule_id|path:line|cwe`), moved from
    `cortexward.agents.memory` to `cortexward.domain.fingerprint` — it turned out to be a
    domain-level identity concept needed by both agent repository-memory suppression and this new
    CLI feature, not agent-specific; `cortexward.agents` still re-exports it for backward
    compatibility. 100%-covered, including a real fixture round-trip (generate a baseline, then
    confirm a `--baseline` scan suppresses exactly that finding while still flagging new ones).
    Along the way, fixed a genuine cross-platform bug this surfaced: `SecretsScanner` now
    constructs `SecretsCollection(root=str(resolved_root))` instead of leaving it defaulted, since
    detect-secrets otherwise computes each secret's reported path via
    `os.path.relpath(..., os.getcwd())`, which raises on Windows whenever the scanned root and the
    process's cwd sit on different drives.
  - **`ci.yml`'s dogfood job now runs `ward scan` on itself**, closing the gap noted above: a
    bash loop invokes `ward scan "$pkg/src" --baseline cortexward-baseline.json --fail-on high`
    once per `packages/*/src` (`ward scan` takes one root at a time), replacing the standalone
    `uvx bandit -r packages/*/src -x "*/tests/*"` step with the full multi-scanner pipeline at
    the same scope. `cortexward-baseline.json` (repo root, generated via `ward baseline`) is
    currently `{"suppressions": []}` — empty, since `src`-only scanning excludes the test
    fixtures where this repo's only known false positives actually live; verified locally with
    the exact loop before committing (every package's `src` scans clean, exit code 0).
- ✅ **`cortexward-server`** (new workspace package): a v1 slice of MPS §20.2's REST API contract.
  `POST /v1/scans` (create a job, 202 Accepted), `GET /v1/scans/{id}` (poll status),
  `GET /v1/scans/{id}/findings` (list results, the full `Finding` shape — evidence included,
  unlike SARIF). Mirrors `ward scan`'s own flags in the request body and reuses
  `cortexward.orchestrator.build_pipeline()`, so a scan behaves identically whether it's driven
  from the CLI or the API. Jobs run via FastAPI's `BackgroundTasks` against an in-memory
  `JobStore` — single-process, no persistence (`StoragePort` has no adapter yet to persist into).
  **Deliberately not implemented**: authentication, rate-limiting, per-finding `verify`/`fix`
  endpoints, `GET /v1/runs/{id}/manifest`, `POST /v1/webhooks/{provider}` — each needs
  infrastructure (a persisted finding store, a `VCSPort` adapter, ...) that doesn't exist yet;
  this is a single-tenant, trusted-caller tool today, not something to expose on an untrusted
  network. 100%-covered via FastAPI's `TestClient` against the real app (real `BanditScanner`,
  no mocking), plus a genuine end-to-end run against the real local Ollama server — skipped when
  none is reachable.
- ✅ **`ward serve`** wires the REST API into the CLI: `uvicorn.run("cortexward.server.app:app",
  host, port, reload)`. `cortexward-cli` gains `cortexward-server`/`uvicorn` as hard dependencies
  (not an optional extra) so the command genuinely works out of the box. Verified with a real
  running process, not just tests: started `ward serve`, `POST`ed a real scan request, polled it
  to `"completed"` over an actual HTTP connection, then stopped the exact process by its PID.
  100%-covered (the CLI test monkeypatches `uvicorn.run` itself so tests don't bind a port).
- ✅ **GitHub Action** (`action.yml`, repo root): a composite action wrapping `ward scan`. Checks
  out this repository at a pinned ref (`cortexward-ref`, default `main`) into a side path,
  `uv sync`s it, and runs `ward scan` against the *calling* repository's own checkout — no PyPI
  publish needed, since `cortexward-cli`'s workspace-local dependencies (`cortexward-core`,
  `-orchestrator`, `-reporters`, `-server`) aren't resolvable via a bare `pip install` from a git
  subdirectory URL without the whole monorepo present. Inputs (`path`, `fail-on`, `baseline`,
  `language`) are threaded through `env:` variables into the shell step, never interpolated
  directly into the script string, to avoid the well-known GitHub Actions shell-injection pitfall
  of trusting `${{ inputs.* }}` inline — the same untrusted-input discipline this project applies
  to analyzed source everywhere else (ADR-0004). Results upload via
  `github/codeql-action/upload-sarif`, appearing in the calling repo's Security tab.
  Self-verified end to end on this repo's own CI (`.github/workflows/action-smoke-test.yml`,
  `uses: ./` pinned to `github.sha`): one job scans a known-clean package and asserts exit 0,
  another scans a deliberately vulnerable fixture and asserts exit 1 plus a produced SARIF file —
  a real invocation of `setup-uv`, `uv sync`, `ward scan`, and `upload-sarif`, not a unit test
  double.
- ⏳ GitHub App (bot-driven PR review/comments) and a VS Code extension remain unbuilt.

## Phase 9 — Benchmarks & evaluation ⏳
Datasets with contamination controls (post-cutoff + mutated splits), detection/verification/
patch metrics, and reproducible paper artifacts.

## Phase 10 — v1.0 ⏳
Documentation site, examples, community infrastructure, and the 1.0 release.

---

## Guiding constraints

- One milestone at a time; never leave partially completed work.
- `main` stays green; no feature is complete without tests and docs.
- Every dangerous operation is isolated; analyzed code is untrusted by default.
- Research ideas are captured in [`research/`](research/) as they arise, never lost.
