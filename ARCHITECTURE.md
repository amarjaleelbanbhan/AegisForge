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
> **Status:** living summary. Phases 0–2 are implemented; Phase 3 (scanners), Phase 3.5
> (evaluation), Phase 4 (agents), Phase 7 (repair-gate verification), and Phase 8 (delivery
> surfaces) each have real, shipped subsystems alongside still-open pieces — see §4 below and
> [ROADMAP.md](ROADMAP.md) for the per-phase breakdown. Unbuilt phases are specified as contracts
> in the MPS before they are built.

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

`cortexward-reporters` (depends on `cortexward-core`) ships two `ReporterPort` adapters.
`SarifReporter` renders `Finding`s into a SARIF 2.1.0 document — one `run`, one `tool.driver`
(CortexWard itself, not the individual scanners that fed the findings — those show up per-result
in `properties.producers`), one deduplicated rule per distinct `rule_id`, `Severity` mapped to
SARIF's `error`/`warning`/`note` levels. Still export-only, per ADR-0003: `Finding` stays the
richer internal model. `JsonReporter` (`format_id = "cortexward-json"`) is the complement: a
faithful `Finding.model_dump(mode="json")` passthrough carrying every `Evidence` item SARIF's
single-message shape can't express — the place agent-verified findings' reachability/LLM
evidence actually becomes visible (`ward scan --format cortexward-json`). A Semgrep adapter is
what's left of Phase 3.

### 4.3.5 Evaluation harness (Phase 3.5) — *in progress*

Built before the heavy agent work (ADR-0007) so every subsequent capability is measured from the
moment it exists. `cortexward-eval` (depends on `cortexward-core`) ships the `RunManifest` — the
immutable per-run provenance record (evaluation-framework.md §5: git SHA, config hash, dataset,
models with training cutoffs, prompt versions, runtime/hardware, cost, metrics) — and a
deterministic finding-matcher: `match_findings()` pairs predicted `Finding`s against labeled
`GroundTruthFinding`s by CWE compatibility plus location overlap, via greedy bipartite matching in
input order, so TP/FP/FN counts (and everything derived from them — precision, recall, F1) are
reproducible across repeated runs rather than merely plausible. FPR/FNR are redefined as
`1 - precision`/`1 - recall`, since open-ended vulnerability detection has no fixed "negative"
universe the classic `FP / (FP + TN)` formula assumes.

The statistical protocol (§6) is also in place: `bootstrap_ci` is a general, seedable percentile-
bootstrap confidence interval over any statistic of per-example values — "paired bootstrap CIs
over per-example results" is the `statistic=mean` case over per-example deltas, but the function
itself doesn't assume how those per-example values were derived, since the dataset's negative-
example shape isn't decided yet. `mcnemar_test` is the continuity-corrected chi-square test for
matched binary "detected / not" outcomes, using an exact closed-form chi-square(1) CDF (`math.erf`
— a chi-square(1) variable is the square of a standard normal) instead of a `scipy` dependency.
Still missing: the versioned golden dataset with contamination controls, and the
`ward bench run/compare/report` harness contract itself.

### 4.4 Agent framework (Phase 4) — *in progress*

The orchestrator drives specialized agents — Planner, Scanner, Verifier, Repair, Reviewer,
Coordinator, and Memory — over a shared, typed run state. An `LLMPort` abstracts providers
and a **cost-aware router** sends triage to cheap models and reasoning/repair to strong ones.

`cortexward-llm` (depends on `cortexward-core`) ships the LLM abstraction so far. `OllamaAdapter`
implements `LLMPort` against a local Ollama server's `/api/chat` over stdlib `urllib` — no API
key needed (Ollama runs entirely on-device), and the only one of the MPS's six required v1
adapters (native Anthropic, native OpenAI, Gemini, Ollama, OpenAI-compatible, LiteLLM) this
environment can genuinely integration-test, since it has no provider credentials. `cost_estimate`
is always `0.0` (no per-token billing for local inference); `count_tokens` is a documented
~4-chars-per-token heuristic, since Ollama exposes no standalone tokenizer endpoint. A connection
failure raises `OllamaError` rather than degrading silently — unlike a scanner, where one
unreachable source shouldn't abort a whole scan, a caller invoking an LLM adapter is relying on
getting a real completion back. `ModelRouter` is the declarative task-class → model-tier → adapter
router MPS §14 specifies: `TRIAGE`/`REASONING`/`PATCH_GENERATION` route to `CHEAP`/`STRONG` by
default, config-driven and overridable per run, with `offline=True` pinning every task class to
the local tier.

`cortexward-orchestrator` (depends on `cortexward-core`, `cortexward-scanners`,
`cortexward-agents`, and `cortexward-llm`) ships the first `OrchestratorPort` implementation:
`SequentialOrchestrator` runs every configured `ScannerPort` in sequence, then correlates the
results into `Finding`s via `cortexward.scanners.correlate` — no LLM or agent reasoning, just "run
every scanner and merge the results." `default_scanners()` auto-discovers every scanner registered
under `cortexward.scanners`, so a full scan → correlate → SARIF pipeline runs end to end with no
hardcoded scanner list. Unlike its peer adapter packages (cpg, scanners, reporters, eval, llm), the
orchestrator is deliberately *not* isolated from `cortexward.scanners` — coordinating other
adapters is its whole job; `build_pipeline()` (`cortexward.orchestrator.pipeline`) extends that
job to choosing *which* `OrchestratorPort` a request gets — `SequentialOrchestrator` with no LLM
configured, `AgentOrchestrator` with one — so every delivery surface (CLI, REST API, ...) makes
that decision the same, tested way instead of each reimplementing it.

`cortexward-agents` (depends on `cortexward-core`, `cortexward-llm`, `cortexward-scanners`) ships
the framework foundation — `RunState` (stateless functions over shared, typed state), the `Agent`
protocol, `ResilientLLM` (retry + cross-adapter fallback), `run_tool_loop`, versioned/hashed
prompt templates, and the MPS §15 memory abstractions — plus all seven agents built on it and
`AgentOrchestrator`, the agent-driven `OrchestratorPort` implementation. `VerifierAgent` is where
the LLM-insufficiency policy from §2/§4.1 becomes directly observable in agent code: it attaches
an `LLM_ASSESSMENT` `Evidence` via `apply_assessment()`, the same sanctioned lifecycle transition
every other caller uses — no agent-specific bypass exists, so a model can never, by construction,
move a finding to `VERIFIED` on its own. `ReviewerAgent` mirrors the same discipline for patches:
its advisory verdict is a `RunState` note, never a `Patch` gate field. `default_agents()`
assembles the standard Planner → Scanner → Verifier → Repair → Reviewer → Memory → Coordinator
pipeline; a genuine end-to-end run against a real local Ollama server and a real `BanditScanner`
finding backs the unit-test suite.

`VerifierAgent` also attaches the framework's first non-LLM evidence: `CodeGraph` gained
`nodes_at(path, line)` (the reverse of `location_of`), and `build_code_graphs()` auto-discovers
`LanguageProvider`s the way `default_scanners()` discovers scanners. A `REACHABILITY_PROOF`
`Evidence` is attached only on a genuine positive proof from the graph — a finding that isn't
provably reachable is left alone, never treated as refuted, since the entrypoint heuristic
(`main()`/`if __name__ == "__main__":` guards only) is deliberately narrow. This alone can raise a
finding to `TRIAGED`, not `VERIFIED` — reaching that rung needs taint/PoC/differential-test
evidence this framework doesn't produce yet. Still open for Phase 4: a LangGraph-backed
`OrchestratorPort` adapter (`AgentOrchestrator`'s single fixed pass is the reference
implementation, not the only one MPS §13 anticipates), and the taint/PoC/differential-test
evidence needed to actually reach `VERIFIED`.

### 4.5 Verification & sandbox (Phase 6) — *planned*

Progressive isolation: Docker + seccomp/AppArmor by default, optional gVisor/Firecracker for
hardware isolation. Deny-by-default egress, ephemeral environments, and **no build execution
during static analysis**. The sandbox realizes rungs 3–4 of the ladder and stores PoC
artifacts referenced by `Evidence.artifact_ref`.

### 4.6 Repair (Phase 7) — *in progress*

Minimal-diff patches, never auto-merged. Every patch passes four gates before it is offered:
applies cleanly, existing tests still pass, scanners re-run clean, and **the original PoC no
longer succeeds against the patched code**. This closes the loop: the same evidence that proved
the bug proves the fix. `RepairAgent`/`ReviewerAgent` (§4.4) generate the diff and give an
advisory LLM review; `cortexward.agents.patch_gates.apply_and_rescan()` is the genuine
verification for the two gates that don't need sandboxed execution — it copies only the touched
files into a scratch directory, applies the diff via `git apply` (a trusted external tool, never
the analyzed project's own code), and re-runs the same scanners against the patched copy. The
diff is LLM output, so it's treated as untrusted per ADR-0004: `Patch.files_changed` is validated
against path traversal and absolute/drive-letter paths with OS-independent string logic before
anything is read or written. Only a genuine result ever sets `Patch.rescan_clean`; an
inconclusive one (didn't apply, `git` missing, ...) is left alone rather than guessed at. The
remaining two gates — existing tests pass, PoC neutralized — need to execute the analyzed
project's own code, which needs §4.5's sandbox and doesn't exist yet: `Patch.is_validated`
correctly stays `False` until then, even for a patch that already passed both available gates.

### 4.7 Delivery surfaces (Phase 8) — *in progress*

CLI (Typer), REST API (FastAPI), GitHub App / Action, and a VS Code extension — how CortexWard is
actually invoked, as opposed to the library-only building blocks the earlier phases ship.

`cortexward-cli` (depends on `cortexward-orchestrator` and `cortexward-reporters`) ships first,
pulled forward from strict phase order: `ci.yml`'s dogfood job had long carried a comment noting
it stood in for `ward scan .` "until cortexward-scanners exists," and by the time the orchestrator
landed that condition was already met. `ward scan <path>` wires `default_scanners()` →
`SequentialOrchestrator` → `SarifReporter` into a runnable tool (SARIF to stdout or `--output
FILE`, `--language` filtering, `--fail-on` controlling the exit code). It is **not** wired into
`ci.yml` yet: scanning this repo's own `packages/` surfaces real false positives in test fixtures
(the detect-secrets adapter's own deliberately-fake secret literals, and the literal word
"secret" in `detect-secrets = "..."` entry-point declarations) that a findings-suppression/
baseline mechanism would need to mark accepted — without one, the dogfood job would fail on every
push for reasons that aren't real vulnerabilities.

`ward scan --llm-provider <name> --llm-model <model>` (or `--llm-config <yaml>`) swaps in
`AgentOrchestrator` for `SequentialOrchestrator`, so findings carry real LLM verification and
reachability evidence instead of raw scanner output — with no LLM flags given, behavior is
unchanged. `--reachability`/`--no-reachability` toggles the `build_code_graphs()` step. This is
the first delivery-surface wiring for the whole agent framework built in §4.4; previously
`AgentOrchestrator` was reachable only from tests. `--format` picks the `ReporterPort` to render
via the plugin registry (`sarif` default, or `cortexward-json` to actually see the evidence the
`--llm-provider` pipeline attaches — SARIF's `properties.state` reflects the outcome but not the
evidence itself).

`cortexward-server` (depends on `cortexward-orchestrator`, `cortexward-llm`, `fastapi`) ships a
v1 slice of MPS §20.2's REST API: `POST /v1/scans` (202 Accepted), `GET /v1/scans/{id}` (poll
status), `GET /v1/scans/{id}/findings` (the full `Finding` shape, not SARIF's narrowed one). The
request body mirrors `ward scan`'s CLI flags and reuses the same `build_pipeline()`, so a scan
behaves identically from either surface — this is the payoff of extracting that function rather
than leaving it private to the CLI. Jobs run via FastAPI's `BackgroundTasks` against
`JobStore` (`cortexward.server.jobs`) — thread-safe, in-memory, single-process; no persistence,
since `StoragePort` has no adapter yet to persist into, and no auth/rate-limiting, since a
single-tenant trust model is all this project has infrastructure for today. Both limitations are
documented in the module docstring, not silently missing. The GitHub App/Action and VS Code
extension are what's left of Phase 8.

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
