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
- ⏳ A LangGraph-backed orchestrator adapter and the seven agents themselves (Planner, Scanner,
  Verifier, Repair, Reviewer, Coordinator, Memory) — these need real LLM-driven reasoning to be
  meaningfully testable, which needs the remaining native provider adapters this environment can't
  build without credentials it doesn't have.

## Phase 5 — Threat & architecture reasoning ⏳
STRIDE threat modeling, trust boundaries, attack-surface mapping, and business-logic analysis
grounded on the CPG.

## Phase 6 — Exploit verification ⏳
Sandbox (Docker → gVisor/Firecracker), the full ladder end to end, false-positive reduction,
PoC artifacts, and VEX output.

## Phase 7 — Patch generation ⏳
Minimal-diff automated repair with the three-gate validation (tests pass · rescan clean ·
exploit neutralized) and regression prevention.

## Phase 8 — Delivery surfaces ⏳
CLI (Typer), REST API (FastAPI), GitHub App / Action, and a VS Code extension.

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
