# AegisForge Roadmap

AegisForge is built in strict, shippable phases. Each phase completes a coherent capability
with tests, documentation, and a green CI before the next begins. Phases are capability-based,
not calendar-based: the goal is a system that is always in a releasable state.

Legend: ✅ done · 🚧 in progress · ⏳ planned

---

## Phase 0 — Research & architecture ✅
Analyze the research brief, strengthen the thesis (Verification Ladder + VEX), choose the
architecture (hexagonal, in-process orchestration), and record the roadmap.
- Deliverables: [ARCHITECTURE.md](ARCHITECTURE.md), this roadmap, [`research/`](research/).

## Phase 1 — Foundation 🚧
Repository, tooling, CI, and the pure domain core.
- ✅ `aegisforge` package, `uv`/Ruff/mypy-strict/pytest, `pyproject.toml`.
- ✅ Domain core: `Finding`, `Evidence`, Verification Ladder, `Patch`, `Provenance`,
  `Assessment` — 100% covered, property-tested.
- ✅ CI (lint · format · type · test matrix) + self-audit (secrets, deps).
- ✅ Governance docs, issue/PR templates, Dockerfile, devcontainer.

## Phase 2 — Code intelligence ⏳
Language-agnostic Code Property Graph on tree-sitter (AST → CFG → DFG → call graph), a query
API, and a dependency graph. Python first.
- Enables reachability + taint (ladder rungs 1–2) and grounded LLM retrieval.

## Phase 3 — Scanners ⏳
Adapters for Semgrep, Bandit, secret scanning, and dependency scanning, normalized to the
`Finding` schema, with cross-tool dedup/correlation and SARIF export.

## Phase 4 — Agent framework ⏳
LangGraph orchestrator and agents (Planner, Scanner, Verifier, Repair, Reviewer, Coordinator,
Memory), an `LLMPort` with pluggable backends, and a cost-aware model router.

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
