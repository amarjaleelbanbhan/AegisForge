# 001 — The Verification Ladder

**Status:** foundational · partially implemented (`cortexward.domain.verification`)
**Theme:** core thesis, evidence-calibrated confidence

## Problem

Static analyzers over-report (high recall, low precision); LLM auditors hallucinate and cannot
prove anything; "generate and run an exploit" only works for a narrow band of injection-style
bugs. There is no principled, general way to say *how confident we should be* that a flagged
issue is a real, exploitable vulnerability.

## Hypothesis

If we model verification as a **ladder of increasingly strong evidence**, and calibrate
confidence from the evidence gathered, we can (a) cover all CWE classes, (b) prune false
positives without discarding true ones, and (c) produce trustworthy, explainable verdicts.

```
NONE → STATIC_REACHABILITY → TAINT_CONFIRMED → DYNAMIC_POC → DIFFERENTIAL_TEST
```

Not every vulnerability class can reach the top rung, and that is the point: we report the
*strongest feasible* evidence and score confidence accordingly, rather than forcing every
finding through a runnable-exploit gate it may not admit.

## Approach

- Combine evidence in **log-odds space**; squash with a logistic function so confidence is
  monotonic in supporting evidence and explainable.
- Two structural policies: an LLM cannot climb the ladder or single-handedly verify a finding;
  refutation is scored as first-class negative evidence.
- Map calibrated confidence + highest independent rung to a lifecycle state and a VEX status.

The Phase-1 implementation encodes this; later phases feed it real reachability (Phase 2),
taint (Phase 2/3), and dynamic PoCs (Phase 6).

## Evaluation ideas

- **Precision/recall vs. rung.** Measure how detection precision improves as findings climb
  the ladder, on a labeled benchmark.
- **Ablation.** Disable each rung and quantify its contribution to precision (McNemar's test on
  matched findings).
- **Calibration quality.** Reliability diagrams / Brier score: does a "0.8 confidence" finding
  really turn out true ~80% of the time?
- **FP reduction.** Fraction of static-tool findings de-escalated by refutation evidence.

## Open questions

- What are good default log-odds weights, and can they be *learned* from labeled outcomes
  without overfitting or contaminating evaluation?
- How should multiple independent taint paths or multiple PoCs compound confidence?
- Per-CWE ladder ceilings: which classes can never exceed which rung, and how do we encode that?

## Related

- Implements: [`cortexward/domain/verification.py`](../src/cortexward/domain/verification.py)
- See also: [002 — VEX as a first-class output](002-vex-as-first-class-output.md)
