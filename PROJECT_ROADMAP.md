# CortexWard — Project Completion Roadmap

> **Single source of truth for *remaining* work.** The capability narrative lives in
> [ROADMAP.md](ROADMAP.md); the frozen spec is [MPS-v1.0](docs/specifications/MPS-v1.0.md).
> This file tracks what is left to reach a shippable product, **milestone-driven** (per the
> strategic review): close the core verification loop first, get numbers, get users — not
> completionist phase-marching. Audited 2026-07-22 against the actual codebase, not the docs.

## 1. Completion summary

CortexWard is an autonomous AI software-security engineer: 13 workspace packages, hexagonal
architecture, 100 %-coverage gate, green CI. The audit found **no core stubs, no `TODO`/`FIXME` in
`src`, no broken flows.** Every `raise NotImplementedError` is a *documented-unsupported* branch.

The architecture is done. The **product loop** was the gap: a user running
`ward scan --llm-provider ollama` on a vulnerable app got a finding at rung 1 (static reachability)
with an LLM advisory verdict — never a dynamically-proven exploit. Milestone 0 closes that.

## 2. Current status (verified this session)

| Gate | Result |
|------|--------|
| `ruff check` / `ruff format --check` | ✅ clean |
| `uv run lint-imports` | ✅ 14 contracts kept, 0 broken |
| `mypy` (per-package) | ✅ all OK |
| `pytest --cov=cortexward --cov-fail-under=100` (baseline audit) | ✅ 1035 passed, 7 skipped (Docker), 100 % |
| Source `TODO`/`FIXME`/core stubs | ✅ none |

Runtime here: **uv 0.11, Ollama present** (live agent + live PoC-generation tests run), **Docker
daemon unreachable** (sandbox live execution tests skip locally, run in CI).

## 3. Report vs. code reconciliation (STEP 2)

The strategic report is context, not truth; verified each claim against the code:

| Area | Report said | Actual code | Status |
|------|-------------|-------------|--------|
| Sandbox | Works in CI, unwired from pipeline | `DockerSandboxAdapter` CI-verified; **now wired** into `PocAgent` | Changed (this session) |
| VerifierAgent | Stuck at rung 1 (reachability) | Still rung 1; rung-3 evidence now produced by the new `PocAgent` | Changed |
| PoC generation | Missing | **Built** — `PocAgent` generates + runs a sandboxed PoC, emits `EXPLOIT_POC` (rung `DYNAMIC_POC`) | Changed |
| Patch gates | 2 of 4 (apply + rescan) | Still A+C; B (tests) / D (PoC-neutralized) remain | Confirmed |
| Cross-file CPG | Same-file only | Same-file only (`_call_graph_builder`) | Confirmed |
| LLM adapters | 6 built, only Ollama live-tested | Confirmed | Confirmed |
| CLI | `ward scan/bench/threat-model/baseline/serve` work | Confirmed; `--sandbox` PoC wiring pending | Confirmed |
| Tests | 100 % coverage, strict | Confirmed (1035 passed) | Confirmed |
| Delivery surfaces | CLI/API/Action/VSCode all present | Confirmed | Confirmed |

## 4. Milestones (priority order)

### Milestone 0 — Close the core verification loop  🟡 IN PROGRESS
Detection → Verification → **PoC → Sandbox → `DYNAMIC_POC` evidence** → VERIFIED → Patch → gates → SARIF/VEX.

- [x] **`PocAgent`** (`cortexward.agents.poc`): generates a PoC via LLM, runs it in `SandboxPort`,
  attaches supporting `EXPLOIT_POC` evidence at rung `DYNAMIC_POC` **only** on a genuine
  marker-trigger (unguessable per-finding token echoed only as a side effect of the exploit). One
  CWE class first (CWE-78 command injection). One-directional: a non-triggering/failed/infra-error
  PoC attaches nothing (never a false refutation). Path-escape-guarded bundle. 100 % covered by
  deterministic tests (fake sandbox + scripted LLM).
- [x] **Wired into `default_agents`** between Verifier and Repair, opt-in when `sandbox`+`artifacts`
  +`root` are supplied. A successful PoC → finding `VERIFIED` (rung 3 ≥ TAINT_CONFIRMED) → this is
  what finally gives `RepairAgent` (verified-only) a finding to patch. Byte-for-byte unchanged
  pipeline when the sandbox deps are absent.
- [x] **Live PoC generation verified** against real `qwen2.5-coder:7b` (`TestLivePocGeneration`): the
  model produces a well-formed importlib-loading PoC with the injected marker, which parses and
  bundles correctly. (The generated PoC is deliberately **not** executed on the host — no isolation
  boundary here; execution is the sandbox's job.)
- [ ] **CLI wiring** — `ward scan --sandbox` constructs `DockerSandboxAdapter` + an artifact store
  and threads them through `build_pipeline` so the loop runs from the CLI. ⚠️ *Cannot be live-verified
  in this environment (no Docker daemon); verifiable only in CI / a Docker host.*
- [ ] **Full live loop test** (`TestLivePoc`): real Ollama PoC + real Docker execution against a
  command-injection fixture → asserts genuine `EXPLOIT_POC` evidence + `VERIFIED`. ⚠️ *Needs both
  Ollama and Docker in one environment — neither CI nor this dev box has both; runs only where both
  are installed.*
- [ ] **Gate D + `Patch.is_validated`** — re-run the PoC against the patched copy; set
  `exploit_neutralized` when it no longer triggers; a patch validates only when A+C+B+D all pass.
  (Builds directly on `PocAgent` + `apply_and_rescan`.)

### Milestone 1 — Cross-file Python taint  🔴 NOT STARTED
Inter-module `CALLS` edges (follow `import`s) + inter-procedural taint in `InMemoryCodeGraph.taint()`.
The one technical limit that matters for real Flask/Django apps (source and sink in different modules).
Also widens `PocAgent` bundling from single-file to whole-package.

### Milestone 2 — Real benchmark  🔴 NOT STARTED (partly BLOCKED)
Reproducible FP-reduction measurement: Semgrep-standalone vs CortexWard+verification on real Python
CVEs. Detection metrics + `make reproduce` already exist; the verification/patch metrics unblock once
Milestone 0's `EXPLOIT_POC` evidence flows through a real run. Dataset breadth (SARD/Juliet, mutated
splits) stays ⚠️ BLOCKED on MPS §30 research questions.

### Milestone 3 — First users  🟡 PARTIAL
PyPI package, human-readable default CLI output, docs site, getting-started, blog post. README
already has a verified quickstart; the packaging/publish decision is owner-gated.

### Milestone 4+ — Expand carefully
JS/TS support, then enterprise features. Explicitly **deferred** per the report (do not build now):
MCP server, more VCS providers, pgvector, unauthenticated API hardening, GitHub App.

## 5. Blocked / deferred (do not fake to close)

| Item | Class | Why |
|------|-------|-----|
| Business-logic analysis (Phase 5) | ⚠️ BLOCKED | No concrete analyzable-structure spec |
| `EgressPolicy.ALLOW_LIST`, gVisor/Firecracker | ⚠️ BLOCKED | Missing runtime infra |
| Postgres+pgvector `StoragePort` | ⚠️ BLOCKED | Needs a running Postgres |
| GitHub App (bot PR review) | ⚠️ BLOCKED | Owner-only account action |
| Contamination splits (mutated) | ⚠️ BLOCKED | MPS §30 open research question |

## 6. Testing requirements (unchanged project bar)

Every change keeps the gate green: `ruff check` · `ruff format --check` · `lint-imports` ·
per-package `mypy` · `pytest --cov=cortexward --cov-fail-under=100`. New non-trivial logic ships with
tests using real components over mocks; live paths gated on their infra (Ollama/Docker) and skipped
otherwise. No coverage-gate lowering.

## 7. Production-readiness checklist

- [ ] All gates green on a clean checkout.
- [x] `ward scan`/`bench`/`threat-model`/`baseline`/`serve` run end to end (verified this session).
- [x] `make reproduce` reproduces documented precision/recall/f1 = 1.000.
- [ ] Core loop (`--llm-provider ollama` + sandbox) reaches `DYNAMIC_POC` on a live Docker host.
- [x] No core TODO/FIXME/stub in `src`.
- [ ] All BLOCKED items explicitly documented with their blocker.

## Progress Log

- 2026-07-22 — Audited full repo against source (not docs). Baseline gate green:
  ruff/format/imports/mypy pass; **1035 passed, 7 Docker-skipped, 100 % coverage** (23-min run, live
  Ollama included). Zero core stubs. Created this file.
- 2026-07-22 — Received strategic review; pivoted roadmap to milestone-driven. Reconciled report vs
  code (§3): the sandbox-unwired / rung-1-verifier / no-PoC claims were the live gaps.
- 2026-07-22 — **Milestone 0 core: implemented `PocAgent`** (detect→PoC→sandbox→`DYNAMIC_POC`→VERIFIED),
  wired into `default_agents` (opt-in), 100 % covered (deterministic fake-sandbox tests). Made
  `_parse_poc` robust to real model output (bare ```python fences, no `POC:` prefix) after the first
  live run showed `qwen2.5-coder:7b` returns exactly that. **Live-verified PoC generation** against
  real Ollama: model emits a correct importlib-loading, marker-injecting PoC that parses + bundles.
  Remaining Milestone 0 (CLI `--sandbox` wiring, full Docker+Ollama loop test, Gate D) needs a Docker
  host to verify and is not yet done.
