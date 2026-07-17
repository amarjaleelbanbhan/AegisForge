# CortexWard — Full Technical Review (Phase 1)

**Date:** 2026-07-05
**Reviewer role:** Principal architect / staff security engineer
**Scope:** entire repository at merge of Phase 1 (`Merge Phase 1: foundation and domain core`)
**Companion document:** [Master Project Specification v1.0](../specifications/MPS-v1.0.md) (the forward-looking single source of truth this review feeds into)

> This review deliberately challenges the Phase 1 decisions rather than ratifying them. Each
> issue states the problem, a recommendation, the migration cost, the long-term benefit, and a
> **now / soon / later** verdict. Items marked **now** are cheap today and expensive later.

---

## 1. Executive assessment

Phase 1 is a genuinely strong foundation: a pure, 100%-covered domain core; strict typing;
a principled, explainable calibration engine; honest documentation; and CI that dogfoods
security hygiene. The Verification Ladder is a defensible, publishable thesis and is encoded
cleanly.

The risks are **not** in what was built but in what was *deferred to convention*. Five
decisions, if left as-is, will be expensive to change once the codebase and community grow:

1. A **single flat package** where the 3–5 year system needs a **multi-package workspace**.
2. Language, LLM, storage, and orchestration boundaries **named but not contracted** — the ports
   exist in prose, not in code, so nothing yet forces adapters to stay swappable.
3. The **domain model is incomplete** for the real workflow (no `Repository`, `ScanRun`/
   `RunManifest`, `Detector`, `TaintFlow`, `Suppression`, or a finding **fingerprint**).
4. **No persistence, event, or run-provenance model** — yet reproducibility is a headline goal.
5. **Evaluation is documented as a late phase**, contradicting the "benchmark first" mandate.

None require throwing anything away. The domain core survives essentially intact; the work is
*surrounding* it with the right structure before it ossifies. Recommended verdict: **restructure
the workspace and freeze the contracts now (spec + skeleton), implement incrementally.**

---

## 2. Findings by area

### 2.1 Architecture & package layout — **change now**

**Problem.** Everything lives in one importable package `cortexward`. The target system is a
*platform*: core engine, CPG, N language providers, M scanner adapters, LLM adapters, an
orchestrator, a CLI, a REST server, a GitHub App, a VS Code extension, an MCP server, and a
Python SDK. A single package forces all of these — and all their heavy, conflicting
dependencies (tree-sitter grammars, provider SDKs, web frameworks) — into one install and one
release cadence. Contributors cannot own a subsystem; users cannot install a slim core.

**Recommendation.** Adopt a **uv workspace monorepo** of independently versioned packages using
the `cortexward.*` PEP 420 namespace (the model proven by `langchain-core` + partner packages,
and by Rust/JS monorepos):

```
packages/
  cortexward-core/        # domain + ports (no I/O, tiny deps)
  cortexward-cpg/         # code property graph
  cortexward-scanners/    # scanner adapters (extras per tool)
  cortexward-llm/         # provider abstraction + adapters
  cortexward-orchestrator/
  cortexward-cli/
  cortexward-server/      # REST + webhooks
  cortexward-sdk/
```

**Migration cost.** *Low today* — the codebase is ~7 source files. It becomes *high* after
Phase 4. Mechanically: move `src/cortexward/domain` → `packages/cortexward-core/src/cortexward/
domain`, add per-package `pyproject.toml`, declare a `[tool.uv.workspace]`. Tests and imports
are unchanged (`from cortexward.domain import ...` still works via the namespace).

**Long-term benefit.** Independent release/versioning of plugins; slim core install;
per-subsystem ownership and CI; the natural home for third-party plugin packages.

### 2.2 Ports are prose, not code — **change now (as contracts)**

**Problem.** `ARCHITECTURE.md` lists ports (CodeGraph, Scanner, LLM, Sandbox, VCS, Storage,
Telemetry) but none exist as `typing.Protocol`s. "Pluggable" is currently an aspiration the
compiler cannot enforce. The first adapter written without a contract will leak its shape into
callers and quietly become load-bearing.

**Recommendation.** Define the ports as `Protocol`s in `cortexward-core` **before** any adapter,
plus an entry-point-based plugin registry. Adapters then depend on core; core depends on none of
them. This is the single most important structural safeguard for a plugin platform.

**Verdict:** specify all ports in the MPS now; land the `Protocol` skeletons with each phase that
first needs them. No adapter merges without its port.

### 2.3 Domain model gaps — **change soon (spec now)**

The Phase 1 model (`Finding`, `Evidence`, `Provenance`, `Patch`, `SourceLocation`, `Assessment`)
is clean but insufficient for the end-to-end workflow. Missing, in rough priority order:

| Missing concept | Why it matters | When |
|---|---|---|
| **Finding fingerprint** (stable dedup/correlation key) | Cross-tool dedup and cross-run tracking are impossible without it; every SAST platform needs it | soon |
| `Repository`, `Revision/Commit`, `AnalysisTarget` | The unit of work; scoping; provenance anchor | soon |
| `ScanRun` / **`RunManifest`** | Reproducibility & experiment tracking (headline goal) | soon |
| `Detector` / `Rule` / `CweRef` | `rule_id: str` is too weak; rules need metadata, versions, provenance | soon |
| `Source` / `Sink` / `TaintFlow` | First-class taint evidence for rungs 1–2 | Phase 2 |
| `Suppression` / triage decision | Memory/feedback loop; auditability | Phase 4 |
| `SandboxExecution` result | PoC artifacts for rungs 3–4 | Phase 6 |

**Fingerprint** deserves emphasis: define it now as a deterministic hash over
`(normalized_rule, file, structural_location, code_snippet_hash)` so it survives reformatting and
line shifts. Retrofitting a fingerprint after data exists is painful.

### 2.4 Persistence, events & provenance — **change soon**

**Problem.** There is no persistence model and no event model. Findings *evolve* as evidence
accrues; the natural, reproducibility-friendly representation is an **append-only evidence log
with a materialized finding state**, not CRUD over a mutable row. The current `Finding.
with_evidence` already hints at this functional style — persistence should match it.

**Recommendation.** Specify: an event/evidence log (append-only) + materialized read models;
Postgres + `pgvector` for retrieval; content-addressed artifact store (filesystem/S3) for PoCs
and SARIF; SQLite as the zero-config local backend behind the same `StoragePort`. Keep the DB
schema **separate** from the domain model (no ORM types in the domain).

### 2.5 LLM abstraction — **spec now, implement Phase 4**

**Problem.** The brief now requires Anthropic, OpenAI, Gemini, Ollama, vLLM, and
LiteLLM-compatible providers. A naive choice is to depend on LiteLLM as *the* abstraction — that
trades six lock-ins for one.

**Recommendation.** Own a minimal `LLMClient` protocol (structured output, tool-calling, token
accounting, streaming, cost) in `cortexward-llm`. Ship *native* adapters for Anthropic and
OpenAI, an OpenAI-compatible adapter (covers vLLM and most gateways), an Ollama adapter, and a
**LiteLLM adapter as a catch-all** — LiteLLM becomes one interchangeable backend, not the spine.
Add a **cost-aware router** and **versioned, hashed prompts** for provenance.

### 2.6 Orchestration lock-in — **spec now**

**Problem.** ADR-0002 commits to LangGraph. LangGraph is capable but young and fast-moving; its
types must not become the application's interface for a 3–5 year core.

**Recommendation.** Define an `Orchestrator`/`AgentGraph` port; LangGraph is *one* adapter behind
it. Domain and application layers never import LangGraph. This preserves the ADR-0002 benefit
(inspectable state machine) while removing the lock-in.

### 2.7 Language coverage — **spec now, Python first**

**Problem.** Seven languages are required "without major architectural changes," but there is no
`LanguageProvider` contract yet.

**Recommendation.** Specify a `LanguageProvider` port (parse→CPG, entry-point detection, source/
sink catalogs, dependency-manifest parsing, build-metadata extraction *without executing builds*)
and a capability matrix per language. Implement Python end-to-end first as the reference; every
other language is an adapter validated against the same conformance test suite.

### 2.8 CI/CD gaps — **change soon (infra, not features)**

Current CI is good; for a flagship it is missing: a committed **`uv.lock`** (reproducible
installs — notably absent), a **coverage threshold gate**, **dogfooding** (run CortexWard/Semgrep
on itself and upload SARIF to code scanning), **SBOM** generation (CycloneDX), **release
automation** with signed artifacts and **SLSA provenance/attestations**, Dependabot/Renovate, and
a broader OS matrix (development is on Windows; CI is Linux-only). These are hygiene, not
features; schedule immediately after MPS approval.

### 2.9 Security architecture — **deepen in MPS**

Phase 1 states the right *intentions* (untrusted input, no self-approval tool, egress-deny) but
lacks a **trust-boundary diagram**, a per-component **STRIDE** table, a concrete **sandbox
execution contract**, and a **secret-redaction pipeline** specification. The MPS makes these
normative. This is the area most scrutinized by both security users and paper reviewers.

### 2.10 Evaluation is mis-sequenced — **change now (roadmap)**

**Problem.** ROADMAP puts benchmarks at Phase 9. The mandate is *benchmark first*: every feature
must move a measured metric. Building agents before the harness means months of unmeasured work.

**Recommendation.** Introduce an **evaluation harness + golden dataset + `RunManifest`** as an
early phase (right after CPG and scanners, before heavy agents). Reorder the roadmap accordingly
(see MPS §Roadmap). This is the single highest-leverage process change.

### 2.11 Smaller notes

- **Naming.** `Provenance.producer: str` should become a typed producer reference backed by a
  registry once adapters exist. `Finding.related_ids` needs typed relationship semantics
  (duplicate-of, same-root-cause). Minor; track in the domain spec.
- **`Assessment` thresholds** are module constants; they should be a versioned, overridable
  `CalibrationProfile` so research can tune and record them per run.
- **Docs duplication.** `ARCHITECTURE.md` and the two Open-Source-Strategy sections of the
  research report overlap. After MPS approval, `ARCHITECTURE.md` should become a *summary that
  links into* the MPS, which is the single source of truth.
- **`py.typed` shipping.** Confirm the marker is included in the wheel once packages split.

---

## 3. What must NOT change

To avoid churn for its own sake, these Phase 1 decisions are ratified:

- The **Verification Ladder** thesis and its log-odds calibration (ADR-0001).
- **Evidence-over-assertion** and the *LLM-is-never-sufficient* policy encoded in code.
- **VEX/SARIF/SBOM** as first-class outputs (ADR-0003).
- **Hexagonal architecture** and the **pure domain core** discipline.
- Tooling: uv, Ruff, mypy-strict, pytest+hypothesis, Conventional Commits.

---

## 4. Prioritized action list (post-approval)

| # | Action | Verdict | Cost |
|---|--------|---------|------|
| 1 | Restructure to uv workspace + `cortexward.*` namespace | **now** | low |
| 2 | Land port `Protocol`s + plugin registry in `cortexward-core` | **now** | low |
| 3 | Reorder roadmap to benchmark-first; add eval-harness phase | **now** | doc |
| 4 | Add finding **fingerprint** + `Repository`/`ScanRun`/`RunManifest`/`Detector` to domain | **soon** | med |
| 5 | Specify persistence (event log + read models) behind `StoragePort` | **soon** | med |
| 6 | CI hardening: `uv.lock`, coverage gate, dogfood, SBOM, release provenance | **soon** | low–med |
| 7 | `LLMClient` protocol + adapters (+ LiteLLM catch-all) + router | Phase 4 | med |
| 8 | `LanguageProvider` port + conformance suite; Python reference | Phase 2 | med |
| 9 | Orchestrator port with LangGraph adapter | Phase 4 | low |

All of the above are specified normatively in the MPS. Nothing is implemented until the MPS is
approved and the architecture is frozen behind ADRs.
