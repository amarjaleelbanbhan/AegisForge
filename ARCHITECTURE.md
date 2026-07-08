# CortexWard Architecture

> **⚠️ This document is now a summary.** The single source of truth for architecture is the
> **[Master Project Specification v1.0](docs/specifications/MPS-v1.0.md)**, which is **approved
> and frozen**. Changes happen only via [ADRs](docs/adr/README.md). Where this summary and the
> MPS differ, the MPS wins. See also the
> [Phase-1 technical review](docs/reviews/2026-07-05-phase-1-architecture-review.md).

This document gives a fast orientation to the architecture, the reasoning behind the major
decisions, and how the pieces fit together. For normative contracts (ports, domain model,
security, data/DB design, APIs, evaluation), read the MPS.

> **Audience:** engineers extending CortexWard, and reviewers evaluating its design.
> **Status:** living summary. Phase 1 and 1.5 subsystems are implemented; later phases are
> specified as contracts in the MPS before they are built.

---

## 1. Design goals

CortexWard is built to be, simultaneously:

- **Correct and honest** — never assert what it cannot substantiate.
- **Modular and extensible** — scanners, languages, LLMs, and sandboxes are plugins.
- **Reproducible** — identical inputs yield identical results; every result is traceable.
- **Secure by construction** — the code it analyzes is treated as hostile input.
- **Self-hostable** — runs on a laptop with zero external services; scales up when asked.
- **Research-gradeable** — every decision is observable and ablatable.

## 2. The central thesis: evidence over assertion

The defining idea of CortexWard is the **Verification Ladder**. A finding is only as
trustworthy as the strongest *feasible* evidence gathered for it, and different vulnerability
classes admit different evidence:

```
NONE → STATIC_REACHABILITY → TAINT_CONFIRMED → DYNAMIC_POC → DIFFERENTIAL_TEST
```

This replaces the brittle "exploit everything" model (which only works for injection-style
bugs) with a spectrum that covers *all* CWEs while remaining honest about certainty.

Confidence is combined in **log-odds space** and squashed through a logistic function
(`cortexward.domain.verification`). Two policies are enforced structurally:

1. **LLM-insufficiency:** model judgement contributes bounded confidence and *cannot* raise
   a finding's ladder rung. A finding cannot be `VERIFIED` without independent corroboration.
2. **Refutation-as-evidence:** proof that a finding is not exploitable lowers confidence and
   drives a `NOT_AFFECTED` VEX verdict, rather than being silently dropped.

Conclusions are exported as **SARIF** (findings), **VEX** (exploitability), and **CycloneDX**
(SBOM). VEX is a deliberate differentiator: it is the standardized form of the exact question
the ladder answers.

## 3. Architectural style: hexagonal + in-process orchestration

CortexWard follows **hexagonal (ports & adapters)** architecture with a pure domain core.

```
┌────────────────────────────────────────────────────────────────────┐
│ Interfaces        CLI · REST API · GitHub App · VS Code extension    │  cortexward-{cli,server,sdk}
├────────────────────────────────────────────────────────────────────┤
│ Application       Orchestrator (state machine)                       │  cortexward-orchestrator
│                   Planner → Scanner → Verifier → Repair → Reviewer   │
│                   Coordinator · Memory                               │
├────────────────────────────────────────────────────────────────────┤
│ Domain core       Finding · Evidence · Verification Ladder ·         │  ┐
│ (pure, no I/O)    Patch · Provenance · Assessment                    │  │
├────────────────────────────────────────────────────────────────────┤  │ cortexward-core
│ Ports             CodeGraph · LanguageProvider · Scanner · LLM ·      │  │ (implemented,
│ (Protocols)       Sandbox · VCS · Storage · Telemetry ·               │  │  Phase 1/1.5)
│                   Orchestrator · Reporter                             │  │
├────────────────────────────────────────────────────────────────────┤  │
│ Plugin registry   Entry-point discovery (cortexward.plugins)          │  ┘
├────────────────────────────────────────────────────────────────────┤
│ Adapters          tree-sitter CPG · Semgrep/Bandit/CodeQL ·          │  cortexward-{cpg,scanners,
│                   Anthropic/OpenAI/Ollama · Docker/gVisor · PyGithub │  llm,sandbox,storage}
│                   · SQLite/Postgres+pgvector · OpenTelemetry          │
└────────────────────────────────────────────────────────────────────┘
```

Each row below "Interfaces" that says *(implemented)* lives in `packages/cortexward-core/`
today; every other row is a sibling package added under `packages/` as its phase lands
([ADR-0005](docs/adr/0005-uv-workspace-monorepo.md)).

**Why in-process orchestration and not microservices?** The research brief proposed
microservices + a message queue. For a tool people install and run in CI, that is premature
operational complexity. We use a single, inspectable orchestrator (a typed state machine, to
be implemented with LangGraph) behind clean ports. Distribution becomes a *later adapter*,
not a founding assumption. Modularity comes from interfaces, not network hops.

### Plugin model

Everything crossing a port is discovered via Python **entry points**
(`importlib.metadata`), through the registry in `cortexward.plugins`. Adding a scanner, a
language front-end, a verifier, or an LLM backend is a matter of shipping a package that
registers under the relevant `PluginGroup` — no core changes required. The registry never
imports an adapter package directly; it resolves entry points by name at runtime.

### Import boundaries

The dependency direction above is enforced mechanically, not just by convention:
**import-linter** contracts (in the root `pyproject.toml`) forbid `cortexward.domain` and
`cortexward.ports` from importing any adapter, application, or interface package, and a
`layers` contract fixes `plugins > ports > domain`. `uv run lint-imports` runs in CI on every
push.

## 4. Subsystems

### 4.1 Domain core (`cortexward.domain`) — *implemented*

Pure model and services with no I/O:

- `enums` — `Severity`, `VerificationRung`, `EvidenceKind`, `FindingState`, `VexStatus`.
- `models` — `SourceLocation`, `Provenance`, `Evidence`, `Patch`, and the `Finding` aggregate.
- `value_objects` — `Assessment` (derived conclusions).
- `verification` — the calibration engine (`calibrate_confidence`, `assess`, `apply_assessment`).

Findings are updated functionally (`with_evidence`, `with_state`) so no agent mutates shared
state by accident; the orchestrator threads new values explicitly.

### 4.1b Port catalog & plugin registry (`cortexward.ports`, `cortexward.plugins`) — *implemented*

The full port catalog from MPS §17.1 exists today as `typing.Protocol` contracts, each owning
its own small request/response DTOs so the domain model stays free of port concerns:
`LanguageProvider`, `CodeGraph`, `ScannerPort`, `LLMPort`/`EmbeddingPort`, `SandboxPort`,
`VCSPort`, `StoragePort`, `TelemetryPort`, `OrchestratorPort`, `ReporterPort`. No adapters
exist yet — these are the contracts future scanner/LLM/sandbox/VCS packages implement against.

`cortexward.plugins` provides `PluginGroup` (the canonical entry-point group per port) and
`PluginRegistry`, which discovers and lazily loads adapters via `importlib.metadata` entry
points. The registry never imports a concrete adapter package.

### 4.2 Code intelligence (Phase 2) — *complete*

A language-agnostic **Code Property Graph** (AST + control-flow + data-flow + call graph), with
a query API. This is the technical moat: it powers reachability and taint analysis *and* grounds
the LLM in retrieved facts instead of raw file dumps, which is the single biggest lever on
hallucination. Python first; other languages are adapters.

`cortexward-cpg` (depends on `cortexward-core`) ships the graph engine: `cortexward.cpg.model`
defines the schema, and `cortexward.cpg.graph` provides `GraphBuilder` plus `InMemoryCodeGraph`
— the reference `CodeGraph` implementation, with cycle-safe reachability/taint/slice queries.
It also ships the Python reference `LanguageProvider` (`cortexward.languages.python`), which
walks a tree-sitter parse tree into the schema's AST layer (`AST_CHILD` edges only) and marks
entry points heuristically, plus a control-flow builder that populates `CFG_NEXT` over that AST
layer (sequential flow, branches, loops with `break`/`continue`, `with`, `return`; each function/
class body is its own scope). `try`/`except`/`finally` is intentionally out of scope for now — a
dedicated exception-flow builder is future work. A data-flow builder then runs an iterative
reaching-definitions analysis over `CFG_NEXT` to populate `DFG_REACHES` (plain/augmented
assignment, `for`-loop targets, and function parameters as definitions; variable references,
excluding attribute/keyword-argument names, as uses) — the def-use graph that grounds taint
analysis (ladder rung 2). A call-graph builder then populates `CALLS` via best-effort, same-file,
name-based resolution (bare-identifier calls against plain functions, attribute calls against
methods), deliberately over-approximating ambiguous same-named matches rather than risking a
missed edge; cross-file and type-aware resolution are future work. Finally,
`cortexward.languages.python.parse_dependencies` reads (never executes) `pyproject.toml`,
`requirements*.txt`, `setup.cfg`, and `Pipfile` into structured `Dependency` records —
`setup.py` is out of scope, since extracting its dependencies reliably needs execution. This
returns plain data rather than `CodeGraph` nodes: the MPS's "dependency graph" layer's exact
node/edge shape isn't pinned down yet, and plain records are exactly what a future
dependency-scanning adapter (Phase 3) needs without forcing that decision early.

### 4.3 Scanners (Phase 3) — *in progress*

Adapters for Semgrep, Bandit, secret scanning, and dependency scanning, each normalizing to
the internal `Finding` schema. Cross-tool **deduplication and correlation** prevents the same
bug being reported three times. SARIF is an export format, not the internal model.

`cortexward-scanners` (depends on `cortexward-core`) ships three adapters so far. `BanditScanner`
invokes `python -m bandit -f json` as a subprocess — a static analyzer that only parses Python's
AST, so this doesn't touch the non-execution guarantee (ADR-0004), which is about *analyzed
project* code, not trusted third-party analysis tools — and maps its JSON results to
`RawFinding`. `SecretsScanner` wraps detect-secrets' native Python API instead (no subprocess,
no binary needed) and is language-agnostic by design; it preserves detect-secrets' one-way hash
of each match, never the plaintext secret, in `RawFinding.raw`. `OsvScanner` queries the public
OSV.dev API for known vulnerabilities in *exactly-pinned* dependencies only (`==X.Y.Z`) — a range
constraint (`>=2.0`) can't be resolved to "the version actually in use" without a lockfile this
scanner doesn't have, and querying OSV without an exact version returns every vulnerability ever
recorded for a package, a poor-quality signal it deliberately avoids; it does its own minimal pin
extraction over stdlib `urllib` rather than depending on Phase 2's `parse_dependencies` (scanner
adapters don't depend on other adapters), and is deliberately network-dependent — unlike the other
two, freshness against the current vulnerability landscape is the point here, not a compromise. A
Semgrep adapter is deferred until an offline, non-registry rule pack is decided — `--config=auto`
needs network access to semgrep.dev, which *does* conflict with this project's offline-determinism
bar (rules changing over time hurts reproducible benchmarking, unlike a vulnerability database's
freshness, which is a feature).

Normalization and correlation are already in place: `cortexward.scanners.normalize` turns one
`RawFinding` into a `Finding` with a single supporting `STATIC_MATCH` `Evidence` at
`VerificationRung.NONE`; `correlate()` runs every scanner's results through it and merges findings
that share a CWE at the same file+line into one `Finding` with multiple `Evidence` entries — the
same real bug reported by several tools becomes one finding, not several. CWE is the only
cross-tool identity signal used; a finding with no CWE never merges with anything.

`cortexward-reporters` (depends on `cortexward-core`) ships the first `ReporterPort` adapter:
`SarifReporter` renders `Finding`s into a SARIF 2.1.0 document — one `run`, one `tool.driver`
(CortexWard itself, not the individual scanners that fed the findings — those show up per-result
in `properties.producers`), one deduplicated rule per distinct `rule_id`, `Severity` mapped to
SARIF's `error`/`warning`/`note` levels. Still export-only, per ADR-0003: `Finding` stays the
richer internal model. A Semgrep adapter is what's left of Phase 3.

### 4.4 Agent framework (Phase 4) — *planned*

The orchestrator drives specialized agents — Planner, Scanner, Verifier, Repair, Reviewer,
Coordinator, and Memory — over a shared, typed run state. An `LLMPort` abstracts providers
and a **cost-aware router** sends triage to cheap models and reasoning/repair to strong ones.

### 4.5 Verification & sandbox (Phase 6) — *planned*

Progressive isolation: Docker + seccomp/AppArmor by default, optional gVisor/Firecracker for
hardware isolation. Deny-by-default egress, ephemeral environments, and **no build execution
during static analysis**. The sandbox realizes rungs 3–4 of the ladder and stores PoC
artifacts referenced by `Evidence.artifact_ref`.

### 4.6 Repair (Phase 7) — *planned*

Minimal-diff patches, never auto-merged. Every patch passes three gates before it is offered:
existing tests still pass, scanners re-run clean, and **the original PoC no longer succeeds
against the patched code**. This closes the loop: the same evidence that proved the bug proves
the fix.

## 5. Cross-cutting concerns

### 5.1 Security of CortexWard itself

The code under analysis is **untrusted, adversarial input**. Concrete threats and defenses:

| Threat | Defense |
|--------|---------|
| Prompt injection via source/comments/READMEs | Source is passed as *data*, never as instructions; no tool exists that lets the model "approve" a finding; structured tool I/O only. |
| Malicious build steps executing during "static" analysis | No build execution in the static phase; parsing only. |
| Sandbox / analysis escape | Deny-by-default egress, ephemeral envs, progressive isolation tiers. |
| Secret exfiltration via LLM APIs | Local-only mode; explicit egress consent; secret redaction before any model call. |
| Supply chain of CortexWard's own deps | `pip-audit` + `gitleaks` in CI (`self-audit` job); pinned, minimal dependencies. |

A full STRIDE threat model is developed in Phase 5 and tracked in [`research/`](research/).

### 5.2 Reproducibility & provenance

Every `Finding`, `Evidence`, and `Patch` carries `Provenance` (producer, version, model, run
id, timestamp). Structured LLM tasks run at temperature 0; scan results are content-addressed
and cached. A run manifest ties every conclusion back to its inputs and tool/model versions —
required for both auditability and research reproducibility.

### 5.3 Observability

OpenTelemetry tracing wraps every agent step, tool call, and model call (added with the agent
framework). This is not optional polish: the ablation studies the research plan depends on
*require* per-step instrumentation, and agentic systems are otherwise undebuggable.

## 6. Technology choices

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Python 3.11+ | Deepest SAST/LLM/parsing ecosystem; matches target code. |
| Models/validation | Pydantic v2 | Strict validation at every boundary against hostile input. |
| Orchestration | LangGraph | Durable, inspectable state machine; enables replay/ablation. |
| Parsing | tree-sitter | Fast, incremental, many grammars; CPG foundation. |
| Scanners (MVP) | Semgrep, Bandit | OSS, fast, strong Python coverage. |
| Sandbox | Docker → gVisor/Firecracker | Progressive isolation without forcing microVMs on all users. |
| Storage | SQLite → Postgres+pgvector | Zero-config local; scales up on demand. |
| Observability | OpenTelemetry + structlog | Trace every step; research-grade instrumentation. |
| Tooling | uv, Ruff, mypy (strict), pytest+hypothesis | Fast, strict, property-tested. |
| Workspace | uv workspace monorepo, `cortexward.*` namespace | Independently versioned packages; slim core install. |
| Import boundaries | import-linter | Mechanically enforces the hexagonal dependency direction. |
| License | Apache-2.0 | Permissive with a patent grant. |

## 7. Decision log

Significant, hard-to-reverse decisions are recorded as short ADR-style entries. Initial set:

- **ADR-0001 — Verification Ladder over binary exploitation.** Covers all CWEs and yields a
  stronger, more honest research claim. (Accepted.)
- **ADR-0002 — In-process orchestration.** Simplicity for self-hosting; scale-out later as an
  adapter. (Accepted.)
- **ADR-0003 — VEX/SARIF/SBOM as first-class outputs.** Standards alignment; VEX matches the
  ladder's core question. (Accepted.)
- **ADR-0004 — Treat analyzed code as hostile input.** Prompt-injection and build-execution
  defenses are foundational, not add-ons. (Accepted.)
- **ADR-0005 — uv workspace monorepo.** Independently versioned packages under `packages/`
  behind the `cortexward.*` namespace; done in Phase 1.5 while migration was still cheap.
  (Accepted.)
- **ADR-0006 — Own the LLM abstraction.** Providers (Anthropic, OpenAI, Gemini, Ollama,
  OpenAI-compatible, LiteLLM) are interchangeable adapters behind `LLMPort`. (Accepted.)
- **ADR-0007 — Benchmark-first roadmap ordering.** The evaluation harness lands at Phase 3.5,
  before the agent framework. (Accepted.)
- **ADR-0008 — Event-sourced findings.** An append-only event log with materialized state,
  matching the domain core's functional update style. (Accepted.)

Future ADRs live alongside the code they govern as the project grows. See the
[full ADR index](docs/adr/README.md) for details on each decision.
