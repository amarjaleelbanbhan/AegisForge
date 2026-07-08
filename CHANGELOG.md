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
