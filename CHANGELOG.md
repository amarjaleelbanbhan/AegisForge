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
