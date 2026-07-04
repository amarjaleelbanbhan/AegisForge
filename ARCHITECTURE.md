# AegisForge Architecture

This document describes the architecture of AegisForge, the reasoning behind the major
decisions, and how the pieces fit together. It is the canonical reference for contributors
and the basis of the research write-up.

> **Audience:** engineers extending AegisForge, and reviewers evaluating its design.
> **Status:** living document. Phase 1 subsystems are implemented; later phases are
> specified here as contracts before they are built.

---

## 1. Design goals

AegisForge is built to be, simultaneously:

- **Correct and honest** — never assert what it cannot substantiate.
- **Modular and extensible** — scanners, languages, LLMs, and sandboxes are plugins.
- **Reproducible** — identical inputs yield identical results; every result is traceable.
- **Secure by construction** — the code it analyzes is treated as hostile input.
- **Self-hostable** — runs on a laptop with zero external services; scales up when asked.
- **Research-gradeable** — every decision is observable and ablatable.

## 2. The central thesis: evidence over assertion

The defining idea of AegisForge is the **Verification Ladder**. A finding is only as
trustworthy as the strongest *feasible* evidence gathered for it, and different vulnerability
classes admit different evidence:

```
NONE → STATIC_REACHABILITY → TAINT_CONFIRMED → DYNAMIC_POC → DIFFERENTIAL_TEST
```

This replaces the brittle "exploit everything" model (which only works for injection-style
bugs) with a spectrum that covers *all* CWEs while remaining honest about certainty.

Confidence is combined in **log-odds space** and squashed through a logistic function
(`aegisforge.domain.verification`). Two policies are enforced structurally:

1. **LLM-insufficiency:** model judgement contributes bounded confidence and *cannot* raise
   a finding's ladder rung. A finding cannot be `VERIFIED` without independent corroboration.
2. **Refutation-as-evidence:** proof that a finding is not exploitable lowers confidence and
   drives a `NOT_AFFECTED` VEX verdict, rather than being silently dropped.

Conclusions are exported as **SARIF** (findings), **VEX** (exploitability), and **CycloneDX**
(SBOM). VEX is a deliberate differentiator: it is the standardized form of the exact question
the ladder answers.

## 3. Architectural style: hexagonal + in-process orchestration

AegisForge follows **hexagonal (ports & adapters)** architecture with a pure domain core.

```
┌────────────────────────────────────────────────────────────────────┐
│ Interfaces        CLI · REST API · GitHub App · VS Code extension    │
├────────────────────────────────────────────────────────────────────┤
│ Application       Orchestrator (state machine)                       │
│                   Planner → Scanner → Verifier → Repair → Reviewer   │
│                   Coordinator · Memory                               │
├────────────────────────────────────────────────────────────────────┤
│ Domain core       Finding · Evidence · Verification Ladder ·         │
│ (pure, no I/O)    Patch · Provenance · Assessment                    │
├────────────────────────────────────────────────────────────────────┤
│ Ports             CodeGraph · Scanner · LLM · Sandbox ·              │
│ (interfaces)      VCS · Storage · Telemetry                          │
├────────────────────────────────────────────────────────────────────┤
│ Adapters          tree-sitter CPG · Semgrep/Bandit/CodeQL ·          │
│                   Anthropic/OpenAI/Ollama · Docker/gVisor · PyGithub │
│                   · SQLite/Postgres+pgvector · OpenTelemetry          │
└────────────────────────────────────────────────────────────────────┘
```

**Why in-process orchestration and not microservices?** The research brief proposed
microservices + a message queue. For a tool people install and run in CI, that is premature
operational complexity. We use a single, inspectable orchestrator (a typed state machine, to
be implemented with LangGraph) behind clean ports. Distribution becomes a *later adapter*,
not a founding assumption. Modularity comes from interfaces, not network hops.

### Plugin model

Everything crossing a port is discovered via Python **entry points**
(`importlib.metadata`). Adding a scanner, a language front-end, a verifier, or an LLM backend
is a matter of shipping a package that registers under the relevant entry-point group — no
core changes required.

## 4. Subsystems

### 4.1 Domain core (`aegisforge.domain`) — *implemented*

Pure model and services with no I/O:

- `enums` — `Severity`, `VerificationRung`, `EvidenceKind`, `FindingState`, `VexStatus`.
- `models` — `SourceLocation`, `Provenance`, `Evidence`, `Patch`, and the `Finding` aggregate.
- `value_objects` — `Assessment` (derived conclusions).
- `verification` — the calibration engine (`calibrate_confidence`, `assess`, `apply_assessment`).

Findings are updated functionally (`with_evidence`, `with_state`) so no agent mutates shared
state by accident; the orchestrator threads new values explicitly.

### 4.2 Code intelligence (Phase 2) — *planned*

A language-agnostic **Code Property Graph** (AST + control-flow + data-flow + call graph) on
tree-sitter, with a query API. This is the technical moat: it powers reachability and taint
analysis *and* grounds the LLM in retrieved facts instead of raw file dumps, which is the
single biggest lever on hallucination. Python first; other languages are adapters.

### 4.3 Scanners (Phase 3) — *planned*

Adapters for Semgrep, Bandit, secret scanning, and dependency scanning, each normalizing to
the internal `Finding` schema. Cross-tool **deduplication and correlation** prevents the same
bug being reported three times. SARIF is an export format, not the internal model.

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

### 5.1 Security of AegisForge itself

The code under analysis is **untrusted, adversarial input**. Concrete threats and defenses:

| Threat | Defense |
|--------|---------|
| Prompt injection via source/comments/READMEs | Source is passed as *data*, never as instructions; no tool exists that lets the model "approve" a finding; structured tool I/O only. |
| Malicious build steps executing during "static" analysis | No build execution in the static phase; parsing only. |
| Sandbox / analysis escape | Deny-by-default egress, ephemeral envs, progressive isolation tiers. |
| Secret exfiltration via LLM APIs | Local-only mode; explicit egress consent; secret redaction before any model call. |
| Supply chain of AegisForge's own deps | `pip-audit` + `gitleaks` in CI (`self-audit` job); pinned, minimal dependencies. |

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

Future ADRs live alongside the code they govern as the project grows.
