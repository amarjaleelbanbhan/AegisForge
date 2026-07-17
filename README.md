<div align="center">

# 🛡️ CortexWard

**An autonomous AI software security engineer that understands, verifies, fixes, and secures software.**

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-pre--alpha-orange.svg)](ROADMAP.md)
[![CLI](https://img.shields.io/badge/CLI-ward_scan-2a6db2.svg)](packages/cortexward-cli)
[![Typed](https://img.shields.io/badge/typed-mypy_strict-2a6db2.svg)](pyproject.toml)

</div>

---

> **Status: Pre-alpha.** Phases 0–2 (foundation, workspace, Code Property Graph engine) are
> complete; Phase 3 (scanners) has Bandit, detect-secrets, and OSV.dev adapters with cross-tool
> correlation and SARIF export; Phase 3.5 (evaluation) and Phase 4 (agents) have their
> foundational, non-LLM-dependent pieces (`RunManifest`, the statistical protocol, the LLM
> abstraction, and a sequential orchestrator) in place. The `ward` CLI (Phase 8) already runs a
> real scan end to end — see [Try it](#try-it) below. CortexWard is being built one milestone at
> a time — see the [Roadmap](ROADMAP.md) for exactly what's done versus planned per phase.
>
> 📐 **Single source of truth:** the [Master Project Specification v1.0](docs/specifications/MPS-v1.0.md)
> is **approved and frozen**. Architecture changes only via [ADRs](docs/adr/README.md). See the
> [Phase-1 review](docs/reviews/2026-07-05-phase-1-architecture-review.md) and the
> [Evaluation Framework](docs/benchmark/evaluation-framework.md).

## Why CortexWard

AI writes a large and growing share of the world's code, and studies repeatedly find
that **30–40% of AI-generated code ships with security flaws**. Existing tools each see
only part of the picture:

- **Static analyzers** (Semgrep, CodeQL, Bandit) match patterns but can't tell whether a
  match is actually reachable or exploitable — so they drown teams in false positives.
- **LLM reviewers** reason about intent but hallucinate, and can't *prove* anything.
- **Almost none** close the loop by generating a fix and demonstrating that the fix works.

CortexWard is not another LLM wrapper. It is an **autonomous security engineer**: it builds
a real understanding of a codebase, gathers *evidence* about each potential vulnerability,
and only escalates or fixes what it can substantiate.

## The core idea: the Verification Ladder

Instead of a binary "did an exploit run?", CortexWard assigns each finding the **strongest
feasible evidence** and calibrates its confidence accordingly:

| Rung | Evidence | Meaning |
|------|----------|---------|
| 0 · `NONE` | pattern match | a detector fired |
| 1 · `STATIC_REACHABILITY` | reachability proof | the sink is reachable |
| 2 · `TAINT_CONFIRMED` | data-flow trace | attacker-controlled data reaches the sink |
| 3 · `DYNAMIC_POC` | sandboxed exploit | a proof-of-concept actually worked |
| 4 · `DIFFERENTIAL_TEST` | discriminating test | behaves differently on vulnerable vs. fixed code |

Two safety rules are structural, not aspirational:

1. **An LLM is never sufficient on its own** — model judgement is bounded and cannot climb
   the ladder; only concrete analysis can.
2. **Refutation is first-class** — evidence that a finding *isn't* exploitable is captured
   and drives it toward a `NOT_AFFECTED` verdict.

Results are exported as **SARIF** (findings), **VEX** (exploitability), and **CycloneDX**
(SBOM) — standards-aligned answers to "is this actually a problem in context?"

## Architecture at a glance

CortexWard uses a hexagonal (ports-and-adapters) design with an in-process, inspectable
agent orchestrator. Everything that touches the outside world is a pluggable adapter.

```
Interfaces:   CLI (ward) · REST API · GitHub App · VS Code extension    (packages/cortexward-{cli,server,sdk})
Application:  Orchestrator → Planner · Scanner · Verifier · Repair · Reviewer · Memory
Domain core:  Finding · Evidence · Verification Ladder · Patch · Provenance   ← pure, no I/O
Ports:        CodeGraph · LanguageProvider · Scanner · LLM · Sandbox · VCS
              · Storage · Telemetry · Orchestrator · Reporter   (cortexward.ports, typing.Protocol)
Plugins:      entry-point discovery — a new adapter needs zero core changes (cortexward.plugins)
Adapters:     tree-sitter CPG · Bandit/detect-secrets/OSV.dev · Ollama · SARIF · sequential orchestrator
```

`cortexward-core` ships the domain model, the full port catalog, and the plugin registry.
`cortexward-cpg` (depends on `cortexward-core`) ships the Code Property Graph engine — AST,
control-flow, data-flow, and call-graph builders over tree-sitter, plus dependency-manifest
parsing — and the reference in-memory `CodeGraph` implementation with cycle-safe
reachability/taint/slice queries (Phase 2, complete). `cortexward-scanners` ships `BanditScanner`,
`SecretsScanner` (detect-secrets), and `OsvScanner` (OSV.dev), plus cross-tool normalization and
correlation into `Finding`s. `cortexward-reporters` ships a SARIF 2.1.0 `ReporterPort`.
`cortexward-eval` ships the `RunManifest` provenance record and the statistical protocol
(bootstrap CIs, McNemar's test). `cortexward-llm` ships an `OllamaAdapter` (the only `LLMPort`
backend buildable without provider credentials) and a cost-aware `ModelRouter`.
`cortexward-orchestrator` ships `SequentialOrchestrator`, wiring every auto-discovered scanner
into one correlated `Finding` list. `cortexward-cli` ships `ward scan` on top of all of the
above. Every package is independently versioned under [`packages/`](packages/), added as its
phase lands — see [ARCHITECTURE.md](ARCHITECTURE.md) and
[ADR-0005](docs/adr/0005-uv-workspace-monorepo.md).

## Try it

```bash
uv run ward scan .                       # scan the current directory, SARIF to stdout
uv run ward scan . -o results.sarif      # write SARIF to a file instead
uv run ward scan . --fail-on critical    # only exit non-zero on critical findings
```

`ward scan` auto-discovers every installed scanner (`cortexward.scanners` entry points),
runs each one, correlates their findings by CWE + location into the domain `Finding` model, and
renders the result as SARIF — real, working code, not a roadmap promise.

### GitHub Action

Run CortexWard on any repository's own CI and get results in GitHub's Security tab:

```yaml
- uses: actions/checkout@v4
- uses: amarjaleelbanbhan/CortexWard@main
  with:
    path: .                # what to scan (default: repo root)
    fail-on: high           # none | low | medium | high | critical (default: high)
    baseline: ""            # optional path to a `ward baseline` file
    language: ""            # optional, e.g. "python"
```

Installs `ward` from this repository (pinned via `cortexward-ref`, defaulting to `main`) and
uploads the SARIF report via `github/codeql-action/upload-sarif`. See
[`action.yml`](action.yml).

## Quickstart (development)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). This is a **uv workspace**
(ADR-0005): the root `pyproject.toml` is a virtual manifest, so workspace members must be
synced explicitly with `--all-packages`.

```bash
git clone https://github.com/amarjaleelbanbhan/CortexWard
cd CortexWard
uv sync --all-packages --extra dev

# Run the quality gate exactly as CI does
uv run ruff check packages
uv run ruff format --check packages
for pkg in packages/*/; do uv run mypy "${pkg}src" "${pkg}tests"; done   # per-package, see CONTRIBUTING.md
uv run lint-imports              # hexagonal dependency-direction check
uv run pytest --cov=cortexward --cov-fail-under=100
```

The domain core is usable today:

```python
from cortexward.domain import (
    Finding, Evidence, EvidenceKind, Provenance,
    SourceLocation, VerificationRung, assess,
)

finding = Finding(
    rule_id="py.sql-injection",
    title="Possible SQL injection",
    message="User input flows into a raw SQL query.",
    cwe=89,
    locations=(SourceLocation(path="app/db.py", start_line=42),),
    provenance=Provenance(producer="semgrep", producer_version="1.90"),
).with_evidence(
    Evidence(kind=EvidenceKind.STATIC_MATCH, summary="semgrep rule matched",
             provenance=Provenance(producer="semgrep")),
    Evidence(kind=EvidenceKind.TAINT_TRACE, rung=VerificationRung.TAINT_CONFIRMED,
             summary="request.args → cursor.execute", provenance=Provenance(producer="cpg")),
)

report = assess(finding)
print(report.recommended_state, report.vex_status, round(report.confidence, 2))
# verified under_investigation 0.86
# Corroborated to the taint rung → VERIFIED, but not yet a runnable PoC, so the
# VEX verdict stays "under_investigation" rather than "affected".
```

## Roadmap

CortexWard is built in strict, shippable phases, each with tests, documentation, and a green
CI before the next begins. Phases 0–2 (foundation, workspace, Code Property Graph) are complete.
Phase 3 (scanners) has three adapters, cross-tool correlation, and SARIF export — a Semgrep
adapter and dependency-vulnerability scanning beyond exact-pinned versions remain, both blocked
on design decisions documented in [ROADMAP.md](ROADMAP.md). Phase 3.5 (evaluation) and Phase 4
(agents) have their non-LLM-dependent foundations in place; the LangGraph orchestrator, the seven
agents, and the golden benchmark dataset all need either real LLM-driven reasoning or dataset-
sourcing decisions this environment can't make unilaterally. Phase 8's `ward` CLI was pulled
forward early since scanning was already real. See [ROADMAP.md](ROADMAP.md) for the full,
per-phase breakdown of what's done versus planned.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), our
[Code of Conduct](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md). Research ideas and
open questions live in [`research/`](research/).

## License

[Apache License 2.0](LICENSE).
