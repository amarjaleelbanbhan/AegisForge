# 003 — Contamination-controlled evaluation

**Status:** planned (Phase 9)
**Theme:** benchmark integrity

## Problem

LLMs have memorized large swaths of public vulnerability data (NVD, CVEfixes, SARD/Juliet,
popular GitHub advisories). Evaluating an LLM-based security tool on that same public data
measures *memorization*, not *capability* — and inflates every reported metric. The research
brief proposes using exactly these sources without addressing contamination, which would
undermine any published result.

## Hypothesis

Reported detection/verification/patch metrics on public benchmarks are significantly inflated
by training-data contamination, and controlling for it changes the ranking of approaches.

## Approach

Report on multiple, explicitly-labeled splits:

1. **Memorized split** — well-known public CVEs (expected upper bound; report but discount).
2. **Post-cutoff split** — vulnerabilities disclosed *after* each evaluated model's training
   cutoff. The cutoff is recorded per model as provenance.
3. **Mutated split** — semantically-preserving transformations of known-vulnerable samples
   (renaming, refactoring, control-flow rewrites) that break surface memorization while keeping
   the vulnerability intact.
4. **Novel/synthetic split** — freshly authored vulnerable programs not present in any corpus.

Always report per-split, never a single blended number. Track model + cutoff in run provenance
so results remain interpretable as models change.

## Evaluation ideas

- Quantify the **memorization gap**: metric(memorized) − metric(post-cutoff/mutated).
- Test whether mutation degrades LLM-only detection more than analysis-grounded detection —
  evidence that the ladder's non-LLM rungs add robustness.
- Statistical rigor: paired bootstrap CIs for F1 deltas; McNemar for matched detections.

## Open questions

- How to build mutation operators that are provably vulnerability-preserving?
- How to keep a continuously-refreshed post-cutoff hold-out as models update?

## Related

- Depends on the metrics defined in [ROADMAP.md](../ROADMAP.md) Phase 9.
- Grounds the ablations in [001 — The Verification Ladder](001-verification-ladder.md).
