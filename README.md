<div align="center">

# 🛡️ AegisForge

**An autonomous AI software security engineer that understands, verifies, fixes, and secures software.**

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-pre--alpha-orange.svg)](ROADMAP.md)
[![Typed](https://img.shields.io/badge/typed-mypy_strict-2a6db2.svg)](pyproject.toml)

</div>

---

> **Status: Pre-alpha (Phase 1.5).** The domain core, port catalog, plugin registry, and a
> multi-package workspace are in place. AegisForge is being built one milestone at a time —
> see the [Roadmap](ROADMAP.md).
>
> 📐 **Single source of truth:** the [Master Project Specification v1.0](docs/specifications/MPS-v1.0.md)
> is **approved and frozen**. Architecture changes only via [ADRs](docs/adr/README.md). See the
> [Phase-1 review](docs/reviews/2026-07-05-phase-1-architecture-review.md) and the
> [Evaluation Framework](docs/benchmark/evaluation-framework.md).

## Why AegisForge

AI writes a large and growing share of the world's code, and studies repeatedly find
that **30–40% of AI-generated code ships with security flaws**. Existing tools each see
only part of the picture:

- **Static analyzers** (Semgrep, CodeQL, Bandit) match patterns but can't tell whether a
  match is actually reachable or exploitable — so they drown teams in false positives.
- **LLM reviewers** reason about intent but hallucinate, and can't *prove* anything.
- **Almost none** close the loop by generating a fix and demonstrating that the fix works.

AegisForge is not another LLM wrapper. It is an **autonomous security engineer**: it builds
a real understanding of a codebase, gathers *evidence* about each potential vulnerability,
and only escalates or fixes what it can substantiate.

## The core idea: the Verification Ladder

Instead of a binary "did an exploit run?", AegisForge assigns each finding the **strongest
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

AegisForge uses a hexagonal (ports-and-adapters) design with an in-process, inspectable
agent orchestrator. Everything that touches the outside world is a pluggable adapter.

```
Interfaces:   CLI · REST API · GitHub App · VS Code extension           (packages/aegisforge-{cli,server,sdk})
Application:  Orchestrator → Planner · Scanner · Verifier · Repair · Reviewer · Memory
Domain core:  Finding · Evidence · Verification Ladder · Patch · Provenance   ← pure, no I/O
Ports:        CodeGraph · LanguageProvider · Scanner · LLM · Sandbox · VCS
              · Storage · Telemetry · Orchestrator · Reporter   (aegisforge.ports, typing.Protocol)
Plugins:      entry-point discovery — a new adapter needs zero core changes (aegisforge.plugins)
Adapters:     tree-sitter CPG · Semgrep/Bandit/CodeQL · Anthropic/OpenAI/Ollama · Docker …
```

`aegisforge-core` (this repo's only populated package so far) ships the domain model, the full
port catalog, and the plugin registry. Every other row is an independently versioned package
under [`packages/`](packages/), added as its phase lands — see [ARCHITECTURE.md](ARCHITECTURE.md)
and [ADR-0005](docs/adr/0005-uv-workspace-monorepo.md).

## Quickstart (development)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). This is a **uv workspace**
(ADR-0005): the root `pyproject.toml` is a virtual manifest, so workspace members must be
synced explicitly with `--all-packages`.

```bash
git clone https://github.com/amarjaleelbanbhan/AegisForge
cd AegisForge
uv sync --all-packages --extra dev

# Run the quality gate exactly as CI does
uv run ruff check packages
uv run ruff format --check packages
uv run mypy
uv run lint-imports              # hexagonal dependency-direction check
uv run pytest --cov=aegisforge --cov-fail-under=100
```

The domain core is usable today:

```python
from aegisforge.domain import (
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

AegisForge is built in strict, shippable phases. Phase 1 delivered the foundation and the
tested domain core; Phase 1.5 (this milestone) delivers the workspace restructure, the port
catalog, the plugin registry, and hardened CI. See [ROADMAP.md](ROADMAP.md) for every phase.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), our
[Code of Conduct](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md). Research ideas and
open questions live in [`research/`](research/).

## License

[Apache License 2.0](LICENSE).
