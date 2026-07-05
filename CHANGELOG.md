# Changelog

All notable changes to AegisForge are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Phase 2 (in progress) — Code Property Graph engine.**
  - New workspace package `aegisforge-cpg`, depending on `aegisforge-core`.
  - `aegisforge.cpg.model`: the language-agnostic node/edge schema (`NodeKind`, `EdgeKind`,
    `Node`, `Edge`) unifying AST, control-flow, data-flow, and call edges.
  - `aegisforge.cpg.graph`: `GraphBuilder` and `InMemoryCodeGraph`, the reference implementation
    of the `CodeGraph` port — cycle-safe `reachable`/`taint`/`callers`/`slice`/`location_of`,
    complete and correct over whatever edges exist even before CFG/DFG/call-graph builders land.
  - 100%-covered tests including cycle, diamond-revisit, and self-sink cases.
- **Test infrastructure fix:** adopted pytest's `--import-mode=importlib` and dropped
  `__init__.py` from every package's `tests/` tree, after adding a second workspace package
  revealed a real collision (`tests` as a shared top-level module name). `mypy` now runs once per
  package for the same reason. Test builders (`make_evidence`, `make_finding`) moved from
  importable helpers to pytest fixtures.
- **Phase 1.5 — Workspace & contracts.**
  - Restructured into a **uv workspace monorepo**: `packages/aegisforge-core/` is the first
    independently versioned package; `aegisforge` is now a PEP 420 namespace package so future
    packages (`aegisforge-cpg`, `aegisforge-llm`, ...) can each contribute a subpackage without
    conflict (`ADR-0005`). Package version moves to `aegisforge.core.version()`.
  - The full **port catalog** (`aegisforge.ports`) as `typing.Protocol` contracts:
    `LanguageProvider`, `CodeGraph`, `ScannerPort`, `LLMPort`/`EmbeddingPort`, `SandboxPort`,
    `VCSPort`, `StoragePort`, `TelemetryPort`, `OrchestratorPort`, `ReporterPort` — each with a
    conformance test.
  - The **plugin registry** (`aegisforge.plugins`): entry-point-based discovery and lazy loading
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
  - `aegisforge` package with a pure, framework-free domain core: `Finding`, `Evidence`,
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

[Unreleased]: https://github.com/amarjaleelbanbhan/AegisForge/commits/main
