<div align="center">

# 🛡️ CortexWard

### An autonomous AI security engineer that understands, verifies, fixes, and secures software.

[![CI](https://img.shields.io/badge/CI-passing-2ea44f?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-2ea44f?logo=codecov&logoColor=white)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Typed](https://img.shields.io/badge/typed-mypy_strict-2a6db2.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-pre--alpha-orange.svg)](ROADMAP.md)

**[Quickstart](#try-it) · [Architecture](#architecture-at-a-glance) · [Roadmap](#roadmap) · [Contributing](#contributing)**

</div>

<br>

> **Status: Pre-alpha, but real.** Every command below actually runs — `ward scan` executes a
> real multi-scanner pipeline today, not a roadmap promise. Phases 0–4 (foundation, workspace,
> Code Property Graph, scanners, the full agent framework) are complete. See
> [**§ Roadmap**](#roadmap) for the exact phase-by-phase state, and
> [ROADMAP.md](ROADMAP.md) for the full breakdown with evidence for every line.
>
> 📐 **Single source of truth:** the [Master Project Specification v1.0](docs/specifications/MPS-v1.0.md)
> is **approved and frozen**. Architecture changes only via [ADRs](docs/adr/README.md).

---

## Why CortexWard

AI writes a large and growing share of the world's code, and studies repeatedly find that
**30–40% of AI-generated code ships with security flaws**. Existing tools each see only part
of the picture:

| Tool class | What it does well | Where it falls short |
|---|---|---|
| **Static analyzers** (Semgrep, CodeQL, Bandit) | Fast, broad pattern matching | Can't tell if a match is *reachable* or *exploitable* — drowns teams in false positives |
| **LLM reviewers** | Reason about intent and context | Hallucinate, and can't *prove* anything |
| **Almost every tool** | Detects | Rarely *closes the loop* with a fix it can demonstrate actually works |

CortexWard is not another LLM wrapper. It's an **autonomous security engineer**: it builds a
real understanding of a codebase, gathers *evidence* about each potential vulnerability, and
only escalates or fixes what it can substantiate.

## 🪜 The core idea: the Verification Ladder

Instead of a binary "did an exploit run?", CortexWard assigns each finding the **strongest
feasible evidence** and calibrates its confidence accordingly — climbing higher only when the
evidence earns it:

| Rung | Evidence | Meaning |
|:---:|---|---|
| 0 | `NONE` — pattern match | a detector fired |
| 1 | `STATIC_REACHABILITY` — reachability proof | the sink is reachable |
| 2 | `TAINT_CONFIRMED` — data-flow trace | attacker-controlled data reaches the sink |
| 3 | `DYNAMIC_POC` — sandboxed exploit | a proof-of-concept actually worked |
| 4 | `DIFFERENTIAL_TEST` — discriminating test | behaves differently on vulnerable vs. fixed code |

Two safety rules are **structural, not aspirational**:

- 🚫 **An LLM is never sufficient on its own** — model judgement is bounded and cannot climb
  the ladder; only concrete analysis can.
- ✅ **Refutation is first-class** — evidence that a finding *isn't* exploitable is captured and
  drives it toward a `NOT_AFFECTED` verdict, not silently ignored.

Results are exported as **[SARIF](https://sarifweb.azurewebsites.net/)** (findings),
**[VEX](https://www.cisa.gov/sites/default/files/2023-04/minimum-requirements-for-vex-508c.pdf)**
(exploitability, CycloneDX-VEX), and **CycloneDX SBOM** — standards-aligned answers to
*"is this actually a problem, in context?"*

## Architecture at a glance

CortexWard uses a hexagonal (ports-and-adapters) design with an in-process, inspectable agent
orchestrator. Everything that touches the outside world is a pluggable adapter.

```text
┌─ Interfaces ───────────────────────────────────────────────────────────────────────┐
│  CLI (ward) · REST API · GitHub Action · VS Code extension                         │
├─ Application ────────────────────────────────────────────────────────────────────  │
│  Orchestrator → Planner · Scanner · Verifier · Repair · Reviewer · Memory          │
├─ Domain core (pure, no I/O) ────────────────────────────────────────────────────── │
│  Finding · Evidence · Verification Ladder · Patch · Provenance                     │
├─ Ports (typing.Protocol) ───────────────────────────────────────────────────────── │
│  CodeGraph · LanguageProvider · Scanner · LLM · Sandbox · VCS · Storage · Reporter  │
├─ Plugins ──────────────────────────────────────────────────────────────────────── │
│  entry-point discovery — a new adapter needs zero core changes                     │
├─ Adapters ─────────────────────────────────────────────────────────────────────── │
│  tree-sitter CPG · Bandit/detect-secrets/OSV.dev/Semgrep · Ollama/Anthropic/OpenAI/ │
│  Gemini · SARIF/JSON/CycloneDX-VEX · GitHubVCSAdapter · Docker sandbox · SQLite     │
│  storage · sequential + agent + LangGraph orchestrators                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

<details>
<summary><b>Package map</b> — click to expand</summary>
<br>

| Package | Ships |
|---|---|
| `cortexward-core` | Domain model, full port catalog, plugin registry |
| `cortexward-cpg` | Code Property Graph engine — AST/CFG/DFG/call-graph over tree-sitter, dependency-manifest parsing, reachability/taint/slice queries |
| `cortexward-scanners` | `BanditScanner`, `SecretsScanner` (detect-secrets), `OsvScanner` (OSV.dev), `SemgrepScanner` (self-authored, offline rule pack), cross-tool correlation |
| `cortexward-reporters` | SARIF 2.1.0, CortexWard-native JSON, and CycloneDX-VEX `ReporterPort` adapters |
| `cortexward-eval` | `RunManifest`, detection metrics, statistical protocol (bootstrap CIs, McNemar's test), the versioned golden dataset, and the `ward bench` harness |
| `cortexward-llm` | `LLMPort` adapters — Ollama, Anthropic, OpenAI-compatible, Gemini — plus a cost-aware `ModelRouter` |
| `cortexward-agents` | The seven-agent pipeline (Planner, Scanner, Verifier, Repair, Reviewer, Coordinator, Memory), CPG-grounded reachability evidence, STRIDE threat modeling, patch-gate verification |
| `cortexward-vcs` | `GitHubVCSAdapter`, the first `VCSPort` implementation |
| `cortexward-storage` | `SqliteStoragePort`, the event-sourced finding log (ADR-0008) |
| `cortexward-sandbox` | `DockerSandboxAdapter`, isolated dynamic execution (ADR-0004) |
| `cortexward-orchestrator` | `SequentialOrchestrator`, `AgentOrchestrator`, `LangGraphOrchestrator`, and `build_pipeline()` to pick between them |
| `cortexward-cli` | The `ward` CLI — `scan` / `baseline` / `threat-model` / `bench` / `serve` |
| `cortexward-server` | A REST API slice (FastAPI) |
| `integrations/vscode` | A VS Code extension |

Every package is independently versioned under [`packages/`](packages/), added as its phase
lands — see [ARCHITECTURE.md](ARCHITECTURE.md) and
[ADR-0005](docs/adr/0005-uv-workspace-monorepo.md).

</details>

## Try it

```bash
uv run ward scan .                       # scan the current directory, SARIF to stdout
uv run ward scan . -o results.sarif      # write SARIF to a file instead
uv run ward scan . --fail-on critical    # only exit non-zero on critical findings
uv run ward scan . --format cyclonedx-vex  # render exploitability as CycloneDX-VEX instead
uv run ward scan . --llm-provider ollama --llm-model qwen2.5-coder:7b  # agent-driven verification
```

`ward scan` auto-discovers every installed scanner (`cortexward.scanners` entry points), runs
each one, correlates findings by CWE + location into the domain `Finding` model, and renders
the result — real, working code. With `--llm-provider`, findings carry real LLM verification
and CPG-grounded reachability evidence instead, and `--engine langgraph` swaps in the
LangGraph-backed orchestrator for the identical agent pipeline.

More of the CLI:

```bash
uv run ward baseline . -o cortexward-baseline.json      # accept today's findings, suppress them later
uv run ward scan . --baseline cortexward-baseline.json  # ...then re-scan without re-flagging them
uv run ward threat-model .                              # STRIDE-categorize findings, JSON to stdout
uv run ward bench run <dataset.json> -o run.json         # benchmark against a labeled dataset
uv run ward serve                                        # run the REST API (POST /v1/scans, ...)
```

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
uploads the SARIF report via `github/codeql-action/upload-sarif`. See [`action.yml`](action.yml).

## 🧰 Quickstart (development)

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

# Reproduce the shipped benchmark result in one command
make reproduce
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
CI before the next begins.

| Phase | What it delivers | Status |
|---|---|:---:|
| 0 | Research & architecture | ✅ |
| 1 | Foundation — domain core, CI, tooling | ✅ |
| 1.5 | Workspace & port contracts | ✅ |
| 2 | Code Property Graph engine | ✅ |
| 3 | Scanners (Bandit, Semgrep, secrets, deps) + SARIF | ✅ |
| 3.5 | Evaluation harness — `RunManifest`, golden dataset, `ward bench` | 🚧 |
| 4 | Agent framework — 7 agents, multi-provider LLM, LangGraph engine | ✅ |
| 5 | STRIDE threat modeling, trust boundaries | 🚧 |
| 6 | Sandbox execution, CycloneDX-VEX output | 🚧 |
| 7 | Patch generation, gate validation | 🚧 |
| 8 | CLI, REST API, GitHub Action, VS Code extension | 🚧 |
| 9 | Benchmarks & reproducibility (`make reproduce`) | 🚧 |
| 10 | Docs site, community, v1.0 release | ⏳ |

Every 🚧 phase above is substantially complete with only specific, individually-documented
items left open — see **[ROADMAP.md](ROADMAP.md)** for the full per-phase breakdown, including
exactly what's done, what's next, and why each remaining item is blocked (owner action,
missing infrastructure, or an open research question).

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), our
[Code of Conduct](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md). Research ideas and open
questions live in [`research/`](research/).

## 📄 License

[Apache License 2.0](LICENSE).
