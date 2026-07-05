# CortexWard Roadmap

> **Authoritative ordering:** [MPS §29](docs/specifications/MPS-v1.0.md#29-roadmap). The MPS
> reorders the roadmap to be **benchmark-first** ([ADR-0007](docs/adr/0007-benchmark-first.md)),
> inserting **Phase 1.5** (workspace migration + port contracts + CI hardening) and **Phase 3.5**
> (evaluation harness) ahead of the heavy agent work. This page is the readable summary; the MPS
> table governs.

CortexWard is built in strict, shippable phases. Each phase completes a coherent capability
with tests, documentation, and a green CI before the next begins. Phases are capability-based,
not calendar-based: the goal is a system that is always in a releasable state.

Legend: ✅ done · 🚧 in progress · ⏳ planned

---

## Phase 0 — Research & architecture ✅
Analyze the research brief, strengthen the thesis (Verification Ladder + VEX), choose the
architecture (hexagonal, in-process orchestration), and record the roadmap.
- Deliverables: [ARCHITECTURE.md](ARCHITECTURE.md), this roadmap, [`research/`](research/).

## Phase 1 — Foundation ✅
Repository, tooling, CI, and the pure domain core.
- ✅ `cortexward` package, `uv`/Ruff/mypy-strict/pytest, `pyproject.toml`.
- ✅ Domain core: `Finding`, `Evidence`, Verification Ladder, `Patch`, `Provenance`,
  `Assessment` — 100% covered, property-tested.
- ✅ CI (lint · format · type · test matrix) + self-audit (secrets, deps).
- ✅ Governance docs, issue/PR templates, Dockerfile, devcontainer.

## Phase 1.5 — Workspace & contracts ✅ *(from the MPS review)*
Restructured before the codebase ossified.
- ✅ uv workspace monorepo + `cortexward.*` namespace package
  ([ADR-0005](docs/adr/0005-uv-workspace-monorepo.md)); `cortexward-core` is the first member.
- ✅ Full port catalog as `typing.Protocol` contracts (`cortexward.ports`) with conformance
  tests, and the entry-point plugin registry (`cortexward.plugins`).
- ✅ `import-linter` contracts mechanically enforcing the hexagonal dependency direction.
- ✅ CI hardened for the workspace: `uv.lock` committed, 100% coverage gate, a dogfood security
  scan, and a CycloneDX SBOM artifact. *(Signed release provenance is deferred to Phase 10,
  where release automation is specified — MPS §27.)*

## Phase 2 — Code intelligence 🚧
Language-agnostic Code Property Graph on tree-sitter (AST → CFG → DFG → call graph), a query
API, and a dependency graph. Python first.
- Enables reachability + taint (ladder rungs 1–2) and grounded LLM retrieval.
- ✅ **Graph engine** (`cortexward-cpg`): the node/edge schema (`cortexward.cpg.model`) and the
  reference in-memory `CodeGraph` implementation (`cortexward.cpg.graph`) — `GraphBuilder` plus
  cycle-safe `reachable`/`taint`/`callers`/`slice`/`location_of` queries. Complete and correct
  over whatever edges exist; a graph built from AST alone honestly reports no control/data paths
  until the builders below populate more edges.
- ✅ **Python `LanguageProvider`** (`cortexward.languages.python`): tree-sitter AST parsing into
  the schema above — `detect`/`dependency_manifests`/`parse`, registered under the
  `cortexward.languages` entry-point group. Entry points are marked heuristically (`main()`
  functions and `if __name__ == "__main__":` guards); framework-specific route/handler detection
  is future work.
- ⏳ Control-flow graph builder (populates `CFG_NEXT`).
- ⏳ Data-flow / def-use graph builder (populates `DFG_REACHES`) — enables real taint analysis.
- ⏳ Call graph builder (populates `CALLS`) and dependency-manifest parsing.

## Phase 3 — Scanners ⏳
Adapters for Semgrep, Bandit, secret scanning, and dependency scanning, normalized to the
`Finding` schema, with cross-tool dedup/correlation and SARIF export.

## Phase 3.5 — Evaluation harness ⏳ *(new; benchmark-first)*
Built before advanced agents so every later feature is measured
([ADR-0007](docs/adr/0007-benchmark-first.md), [Evaluation Framework](docs/benchmark/evaluation-framework.md)).
- `cortexward-eval`: metrics, statistical protocol, ablation support.
- A versioned **golden dataset** with contamination controls.
- The immutable **`RunManifest`** (git SHA, config, dataset, model, prompt, runtime, hardware, metrics).

## Phase 4 — Agent framework ⏳
Orchestrator (behind `OrchestratorPort`; LangGraph adapter) and agents (Planner, Scanner,
Verifier, Repair, Reviewer, Coordinator, Memory), an `LLMPort` with pluggable backends, and a
cost-aware model router.

## Phase 5 — Threat & architecture reasoning ⏳
STRIDE threat modeling, trust boundaries, attack-surface mapping, and business-logic analysis
grounded on the CPG.

## Phase 6 — Exploit verification ⏳
Sandbox (Docker → gVisor/Firecracker), the full ladder end to end, false-positive reduction,
PoC artifacts, and VEX output.

## Phase 7 — Patch generation ⏳
Minimal-diff automated repair with the three-gate validation (tests pass · rescan clean ·
exploit neutralized) and regression prevention.

## Phase 8 — Delivery surfaces ⏳
CLI (Typer), REST API (FastAPI), GitHub App / Action, and a VS Code extension.

## Phase 9 — Benchmarks & evaluation ⏳
Datasets with contamination controls (post-cutoff + mutated splits), detection/verification/
patch metrics, and reproducible paper artifacts.

## Phase 10 — v1.0 ⏳
Documentation site, examples, community infrastructure, and the 1.0 release.

---

## Guiding constraints

- One milestone at a time; never leave partially completed work.
- `main` stays green; no feature is complete without tests and docs.
- Every dangerous operation is isolated; analyzed code is untrusted by default.
- Research ideas are captured in [`research/`](research/) as they arise, never lost.
