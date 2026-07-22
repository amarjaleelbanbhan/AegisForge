<div align="center">

# 🛡️ CortexWard — Project Showcase

### An autonomous AI security engineer that *understands, verifies, fixes, and secures* software.

**Apache-2.0 · Python 3.11+ · 13-package hexagonal monorepo · 100% test coverage · mypy-strict**

[GitHub](https://github.com/amarjaleelbanbhan/CortexWard) · [Roadmap](../../ROADMAP.md) · [Architecture](../../ARCHITECTURE.md) · [Contributing](../../CONTRIBUTING.md)

</div>

> This file is the **single source of truth for promoting CortexWard**. Everything here reflects
> what is actually in the repository today. Where something is not yet built or not yet verified,
> it says so. Placeholders are marked `[TODO]` / `[ADD LINK]`.

---

## 🎯 Elevator pitch

Most "AI security" tools produce a verdict: *"this is vulnerable."* They can't show you **why**,
and they're wrong often enough that engineers stop trusting them. CortexWard takes the opposite
stance: **evidence decides, not the model.** It climbs a **Verification Ladder** — from a raw
pattern match, to static reachability, to a taint path, to a **proof-of-concept exploit that
actually runs in a sandbox** — and reports a *calibrated confidence* plus a standards-aligned
**VEX** exploitability status. A language model advises; it can **never, by construction**, mark a
finding "verified" on its own.

---

## ❓ The problem

- Enterprise teams run Bandit + Semgrep + Snyk on every PR and drown in findings — a large share
  are false positives.
- AI-assisted scanners bolt an LLM onto detection and emit confident assertions with no evidence
  trail. In security, a confident wrong answer that *dismisses* a real vulnerability is dangerous.
- Regulations now demand exploitability evidence: **VEX** is a real requirement (US EO 14028,
  EU CRA, CISA), and almost nothing open-source produces VEX grounded in *verification* rather than
  static guessing.

## 💡 Why we built it

To test one thesis: **a vulnerability is only as trustworthy as the strongest evidence gathered for
it.** If you can calibrate confidence across a measurable ladder and *prove* exploitability in
isolation, you can cut false-positive noise honestly — and produce compliance-grade VEX as a
byproduct. That thesis is the project's moat, and it's implemented, not aspirational.

---

## 🧩 The solution — the Verification Ladder

```
NONE  →  STATIC_REACHABILITY  →  TAINT_CONFIRMED  →  DYNAMIC_POC  →  DIFFERENTIAL_TEST
(pattern    (sink reachable      (attacker data     (exploit ran    (test distinguishes
 match)      from entrypoint)     flows to sink)      in sandbox)     vuln vs fixed)
```

Confidence is combined in **log-odds space**: each piece of evidence contributes a signed weight,
squashed through a logistic function — principled, monotonic, explainable. Two safety policies are
baked into the domain model:

1. **An LLM is never sufficient alone.** Model judgements are bounded and *cannot* advance a
   finding up the ladder — enforced structurally in `cortexward.domain.verification`, not by
   convention.
2. **Refutation is first-class.** Positive evidence that something is *not* exploitable drives it
   toward `NOT_AFFECTED`, rather than being ignored.

---

## ⚙️ How it works (end-to-end)

```
        detect            verify (evidence, not opinion)          fix + prove the fix
   ┌───────────────┐   ┌──────────────────────────────────┐   ┌──────────────────────────┐
   │ Bandit        │   │ Verifier   → LLM assessment       │   │ Repair    → minimal diff  │
   │ Semgrep       │──▶│ CPG        → reachability proof    │──▶│ Reviewer  → 4 patch gates │
   │ detect-secrets│   │ PoC agent  → sandboxed exploit ✅  │   │  A applies  C rescan clean│
   │ OSV.dev       │   │            → DYNAMIC_POC evidence  │   │  B tests    D PoC neutral │
   └───────────────┘   └──────────────────────────────────┘   └──────────────────────────┘
          │                          │                                      │
          └──────────── correlate ───┴───── SARIF · CortexWard-JSON · CycloneDX-VEX ─────┘
```

`ward scan --llm-provider ollama --sandbox` runs this whole loop: a finding is detected, an LLM
weighs in (but can't over-promise), the Code Property Graph proves reachability, a **proof-of-concept
is generated and executed inside a locked-down Docker sandbox**, and — only if a unique, unguessable
marker actually fires through the vulnerable code path — the finding reaches `DYNAMIC_POC` → `VERIFIED`.
Then a minimal patch is generated and put through four gates before it can be called validated.

---

## ✨ Key features (all implemented today)

| Feature | What it does |
|---|---|
| **Verification Ladder + calibrated confidence** | Evidence → log-odds confidence → VEX status → lifecycle state, pure & deterministic |
| **Code Property Graph** | tree-sitter Python: AST → CFG → DFG → call graph, with reachability/taint/slice queries (same-file today) |
| **4 scanner adapters** | Bandit, **Semgrep with offline bundled rules** (SSRF, SSTI, hardcoded creds, JWT bypass), detect-secrets, OSV.dev — cross-tool dedup by CWE |
| **Dynamic exploit verification** | LLM-generated PoC executed in an isolated Docker sandbox; marker-based trigger detection → `EXPLOIT_POC` evidence |
| **Four-gate patch validation** | A: applies · B: tests pass (sandbox) · C: rescan clean · D: original PoC neutralized (re-runs the *same* exploit) |
| **Provider-agnostic LLM layer** | Ollama (local, no API key), OpenAI-compatible, Anthropic, Gemini + a cost-aware model router |
| **Standards-aligned outputs** | SARIF 2.1.0, CycloneDX-VEX, a CortexWard-JSON full-evidence format, CycloneDX SBOM |
| **STRIDE threat modeling** | CWE→STRIDE, attack-surface & trust-boundary reasoning grounded on the CPG |
| **Delivery surfaces** | `ward` CLI (Typer), REST API (FastAPI), GitHub Action, VS Code extension |
| **Evaluation harness** | golden dataset + `ward bench` + `make reproduce` (precision/recall/F1) |

---

## 🏛️ Technical architecture

**Hexagonal (ports & adapters), mechanically enforced.** The pure domain core depends on nothing;
every capability is an adapter behind a `typing.Protocol` port; `import-linter` fails the build if
any dependency arrow points the wrong way (14 contracts). This is what lets CortexWard swap LLM
providers, storage backends, or sandbox tiers without touching the domain.

```
              cortexward-core  (domain + ports + plugin registry)   ← depends on nothing
                       ▲
   ┌───────────┬───────┴───────┬────────────┬───────────┬───────────┐
  cpg      scanners        reporters       llm        sandbox     storage   (peer adapters)
   └───────────┴───────────────┴─────┬──────┴───────────┴───────────┘
                              agents / orchestrator      (composition, behind OrchestratorPort)
                                       ▲
                        cli · server · vcs · eval          (delivery surfaces)
```

Key frozen decisions (see [ADRs](../../docs/adr/README.md)):
- **ADR-0001** Verification Ladder over binary "exploit everything"
- **ADR-0002** in-process orchestration behind a port (LangGraph is *one* adapter)
- **ADR-0003** SARIF/VEX/SBOM as first-class outputs
- **ADR-0004** analyzed code is **untrusted input** — never executed outside the sandbox
- **ADR-0005** uv workspace monorepo · **ADR-0006** owned LLM abstraction · **ADR-0007** benchmark-first · **ADR-0008** event-sourced findings

---

## 🧰 Tech stack

- **Language:** Python 3.11+ (mypy-strict, Ruff, 100% branch coverage gate)
- **Packaging:** uv workspace monorepo, 13 `cortexward-*` packages, PEP 420 namespace
- **Parsing / analysis:** tree-sitter, custom CPG (the project's own IP)
- **Scanners:** Bandit, Semgrep, detect-secrets, OSV.dev API
- **LLM:** Ollama / OpenAI-compatible / Anthropic / Gemini behind an owned `LLMPort`
- **Sandbox:** Docker CLI (deny-all network, read-only root, unprivileged, `--cap-drop ALL`, seccomp)
- **Orchestration:** in-process agent pipeline + optional LangGraph `StateGraph`
- **Delivery:** Typer (CLI), FastAPI (REST), GitHub composite Action, VS Code (TypeScript) extension
- **CI:** GitHub Actions — lint · format · mypy · import-boundaries · 100% coverage · Gitleaks · pip-audit · SBOM

---

## 🔒 Implementation details worth knowing

- **The sandbox is genuinely locked down.** `--network none`, `--read-only` root, `--tmpfs /tmp`,
  a *named* output volume (not a host mount), `--user 1000:1000`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, hard wall-clock timeout with an explicit `docker kill`. The
  input bundle is delivered by *building* an ephemeral image, never a host bind-mount. Several of
  these were bug fixes forced by a **real Docker daemon in CI** (e.g. Docker refuses `docker cp`
  into a read-only container).
- **Gate D re-runs the *exact* PoC** that already triggered on the vulnerable code — stored via the
  evidence's `artifact_ref` — against the patched code. "Neutralized" means that same exploit no
  longer fires, not that a command exited zero.
- **Untrusted-input discipline everywhere:** LLM-authored PoCs and diffs are validated for path
  traversal and only ever executed inside the sandbox; symlink-escape and cross-drive path bugs
  were found and fixed along the way.

---

## ✅ What's completed · 🚧 what's in progress

**Completed (Phases 0–8 largely done):** domain core & Verification Ladder · CPG (Python, same-file)
· 4 scanners + correlation · SARIF/JSON/VEX/SBOM · 7-agent pipeline + LangGraph · provider-agnostic
LLM layer (8 selectable providers via 4 adapters) + router · Docker sandbox · **PoC verification loop (`DYNAMIC_POC`)** · **all four patch gates**
· `ward scan/bench/threat-model/baseline/serve` · REST API · GitHub Action · VS Code extension ·
eval harness + `make reproduce`.

**In progress / next:**
- ⏳ **Full live loop end-to-end** (`ward scan --sandbox` on real Docker + real Ollama together) —
  code-complete & CI-green in halves; the combined run is infra-gated (needs both on one host). See
  [OWNER_ACTIONS.md](../../OWNER_ACTIONS.md).
- 🔴 **Milestone 1 — cross-file taint** (inter-module call resolution + inter-procedural taint) — the
  single biggest lever for real Flask/Django apps.
- 🔴 **Milestone 2 — real-CVE benchmark** measuring actual false-positive reduction vs. Semgrep
  standalone.

Honest status: **pre-alpha. Zero external users yet.** That's exactly why this showcase exists.

---

## 🗺️ Roadmap (milestone-driven)

`Milestone 0` close the verification loop *(code-complete)* → `M1` cross-file taint → `M2` real
benchmark → `M3` first users (PyPI, docs site) → `M4` JS/TS → `M5` enterprise foundations.
Full detail: [PROJECT_ROADMAP.md](../../PROJECT_ROADMAP.md) and [ROADMAP.md](../../ROADMAP.md).

---

## 🧠 Challenges solved

- Designing a confidence model that is **monotonic, explainable, and LLM-insufficient by
  construction** — not "an LLM with extra steps."
- Making a Docker sandbox that satisfies a strict non-execution/no-host-mount contract, debugged
  against a real daemon in CI.
- A 13-package monorepo that stays clean: `sys.modules` collisions, per-package mypy, and mechanically
  enforced hexagonal boundaries.
- Parsing real LLM output robustly (models return bare ```python blocks, not the format you asked for).

---

## 🌟 What makes it different

- **Evidence over assertion** — a calibrated ladder, not a yes/no.
- **The LLM-insufficiency rule** — counter-cultural in a market racing to "let AI decide."
- **VEX grounded in verification** — a compliance story, not just a security one.
- **Research-grade rigor** — reproducible metrics, frozen spec + ADRs, 100% coverage.

---

## 🤝 How to contribute

CortexWard is Apache-2.0 and built to be extended — most capabilities are **plugin adapters**
discovered via entry points, so you can add one without touching the core.

**Great first contributions:**
- 🧩 **New scanner adapter** (implement `ScannerPort`, register under `cortexward.scanners`).
- 🤖 **New / live-tested LLM adapter** (Anthropic/Gemini are unit-tested but not live-verified).
- 📄 **New reporter** (e.g. CSAF-VEX, GitLab SAST format) behind `ReporterPort`.
- 🧪 **Widen PoC verification** to another mechanically-verifiable CWE class beyond command injection.
- 🕸️ **Milestone 1: cross-file taint** — inter-module `CALLS` edges + inter-procedural taint (the
  highest-impact area).
- 📚 **Docs, examples, a getting-started tutorial.**

**Good first issues:** `[TODO: create "good first issue" labels on GitHub and link them here]`

**Get started:**
```bash
git clone https://github.com/amarjaleelbanbhan/CortexWard
cd CortexWard
uv sync --all-packages --extra dev

uv run ward scan .                    # scan the current directory (SARIF to stdout)
uv run ward scan . --format cyclonedx-vex
make reproduce                        # regenerate the benchmark metrics

# quality gate exactly as CI runs it
uv run ruff check packages && uv run ruff format --check packages
uv run lint-imports && uv run pytest --cov=cortexward --cov-fail-under=100
```

See [CONTRIBUTING.md](../../CONTRIBUTING.md) and [GOVERNANCE.md](../../GOVERNANCE.md).

---

## 📸 Assets & links

- **Demo GIF (exists):** [`docs/assets/demo-terminal.gif`](../../docs/assets/demo-terminal.gif) — a real `ward scan .` run.
- **Repo:** https://github.com/amarjaleelbanbhan/CortexWard
- **Docs site:** `[ADD LINK — not built yet, Milestone 3]`
- **PyPI:** `[ADD LINK — not published yet, Milestone 3]`
- **Architecture diagram image:** `[TODO: export a clean PNG of the hexagonal diagram for LinkedIn]`
- **PoC-loop GIF:** `[TODO: record ward scan --sandbox reaching DYNAMIC_POC once Docker+Ollama are on one host]`

## 🙏 Credits

Built by **[amarjaleelbanbhan](https://github.com/amarjaleelbanbhan)**. Standing on: tree-sitter,
Bandit, Semgrep, detect-secrets, OSV.dev, Ollama, FastAPI, Typer, LangGraph. Apache-2.0.
