# CortexWard — Evaluation Framework

| | |
|---|---|
| **Version** | 1.0 (companion to [MPS §23](../specifications/MPS-v1.0.md#23-benchmark--evaluation)) |
| **Status** | Proposed (RFC) |
| **Principle** | **Benchmark first.** The harness is built before advanced agents; every feature must move a metric. |

> This document specifies *how CortexWard is measured*. It is normative: it defines the metrics,
> the dataset strategy, the run-provenance record, the statistical protocol, and the harness
> contract. Implemented in the `cortexward-eval` package (roadmap Phase 3.5).

---

## 1. Why benchmark first

If agents are built before the harness, months of work go unmeasured and regressions hide. By
fixing the measurement contract now:

- every PR can report metric deltas (detection F1, FP rate, patch correctness, cost, runtime);
- research claims are reproducible and defensible for artifact evaluation;
- ablations (per ladder rung, per agent, per model) are first-class, not afterthoughts.

## 2. Metrics

All metrics are computed against ground-truth labels on a versioned dataset and recorded in the
[`RunManifest`](#5-runmanifest). Primary metrics are **MUST**.

### 2.1 Detection quality
- **Precision** = TP / (TP + FP)
- **Recall** = TP / (TP + FN)
- **F1** = harmonic mean(precision, recall)
- **False-positive rate** and **false-negative rate**
- Matching of a reported finding to ground truth uses the **fingerprint** + CWE + location overlap
  (a documented matcher, so TP/FP counting is deterministic and reproducible).

### 2.2 Verification quality
- **Verification success rate by rung**: fraction of true findings corroborated to
  `TAINT_CONFIRMED` / `DYNAMIC_POC` / `DIFFERENTIAL_TEST`.
- **FP-reduction**: fraction of static-tool findings correctly de-escalated (`REFUTED`).
- **Calibration**: reliability diagram + **Brier score** — does confidence *c* imply ≈*c* truth?

### 2.3 Patch quality
- **Patch correctness**: fraction of proposed patches passing all three gates (tests pass,
  rescan clean, exploit neutralized).
- **Regression rate**: fraction of patches that break a previously-passing test.
- **Minimality**: diff size vs. reference fix (lines changed).

### 2.4 Cost & efficiency
- **Runtime** (wall-clock, p50/p95) per stage and end-to-end.
- **Compute cost** (CPU/GPU hours) and **token usage** (prompt/completion) per run.
- **Estimated human-review-time saved** — modeled from findings triaged/verified/fixed
  automatically vs. a documented manual-baseline cost per finding (assumptions recorded).

### 2.5 Reporting
Every benchmark run emits a metrics table (Markdown + JSON), a reliability diagram, and a
per-metric comparison to the previous run and to declared baselines.

## 3. Baselines

Comparisons are meaningless without baselines. The harness supports pluggable baselines:

- **Static-only**: Semgrep / Bandit / CodeQL raw output (no verification).
- **LLM-only**: a single-prompt LLM auditor (no ladder, no CPG grounding).
- **Prior AI reviewers** where runnable (e.g. VulnHuntr-style), best-effort.
- **CortexWard ablations**: ladder rung disabled, agent disabled, CPG grounding disabled.

## 4. Dataset strategy

### 4.1 Sources
- **Synthetic**: NIST SARD / Juliet (labeled, CWE-tagged) — breadth and control.
- **Real**: CVEfixes-derived vulnerable+patched pairs from public advisories — realism.
- **Authored/novel**: hand-written vulnerable programs not present in public corpora.

### 4.2 Contamination controls (critical for LLM-based tools)
LLMs memorize public vulnerabilities; naive evaluation measures memorization, not capability.
Every dataset is split and **reported separately** (never blended):

1. **Memorized** — well-known public CVEs (upper bound; reported but discounted).
2. **Post-cutoff** — disclosed after each evaluated model's training cutoff (recorded per model).
3. **Mutated** — semantics-preserving transformations (rename, refactor, control-flow rewrite)
   that break surface memorization while preserving the vulnerability.
4. **Novel** — freshly authored, never published.

Report the **memorization gap** = metric(memorized) − metric(post-cutoff/mutated). See research
note [003](../../research/003-contamination-controlled-evaluation.md).

### 4.3 Versioning & integrity
Datasets are **content-addressed and versioned** (hash manifest; large files via DVC or Git LFS
pointers, not committed blobs). Each example records: CWE, CVSS/severity, ground-truth patch,
source split, and provenance. The dataset version is recorded in every `RunManifest`.

## 5. RunManifest

Every run (production or benchmark) MUST persist an immutable `RunManifest` sufficient to
reproduce it:

```jsonc
{
  "run_id": "run_…",
  "git_sha": "…",                 // exact CortexWard commit
  "config_hash": "…",             // full resolved config
  "calibration_profile": "default@1",
  "dataset": {"name": "ward-bench", "version": "2026.07"},
  "models": [{"task": "reasoning", "provider": "…", "model": "…", "version": "…",
              "training_cutoff": "…"}],
  "prompt_versions": {"detector": "v3", "repair": "v2"},
  "runtime": {"started": "…", "wall_seconds": 812.4},
  "hardware": {"cpu": "…", "gpu": "…|none", "ram_gb": 64, "os": "…"},
  "cost": {"tokens_prompt": 0, "tokens_completion": 0, "usd_estimate": 0.0},
  "metrics": { "precision": 0.0, "recall": 0.0, "f1": 0.0, "fpr": 0.0, "fnr": 0.0,
               "verification_success_by_rung": {}, "patch_correctness": 0.0,
               "regression_rate": 0.0, "brier": 0.0 }
}
```

Manifests are immutable once written and are the unit of comparison across runs.

## 6. Statistical protocol

- **Detection deltas (F1):** paired **bootstrap** confidence intervals over per-example results;
  report the CI and effect size, not just a point estimate.
- **Matched binary outcomes (detected / not):** **McNemar's test** on paired findings.
- **Patch success rates:** chi-square / Fisher's exact between configurations.
- Significance target **p < 0.05**, with multiple-comparison correction across ablations.
- **Ablations (MUST):** disable each ladder rung and each agent; quantify the contribution of each
  to precision/recall/cost. This is the core of the research claim and the reason OTel tracing is
  mandatory from Phase 4.

## 7. Harness contract

`cortexward-eval` exposes:

```
ward bench run <suite> --dataset <version> --config <profile> [--baselines static,llm]
ward bench compare <run-a> <run-b>
ward bench report <run-id> --format md,json
```

- One command reproduces a published result from a `RunManifest`.
- Runs are hermetic where possible (pinned models via local inference for the reproducible tier;
  cloud-model tiers record versions and are reported separately).
- CI runs a **fast smoke suite** on every PR (small dataset, deterministic tiers) and gates on
  no-regression of primary metrics; the **full suite** runs on a schedule / release.

## 8. Artifact evaluation readiness

For top-venue submission, the harness packages: pinned code (git SHA), dataset manifest, configs,
`RunManifest`s, and a `make reproduce` target that regenerates the paper's tables and figures.
Everything a reviewer needs to re-run is versioned and documented.

## 9. Roadmap placement

The harness, a **golden dataset**, and the `RunManifest` land in **Phase 3.5**, immediately after
scanners and *before* the heavy agent work of Phase 4 — so every subsequent capability is measured
from the moment it exists.
