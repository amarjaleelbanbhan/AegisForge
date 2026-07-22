# Post 2 — Technical Deep Dive

**Purpose:** Earn serious engineers with the confidence model + LLM-insufficiency rule.
**When to post:** Third (after Launch and Feature Spotlight).
**Attach:** `docs/linkedin/assets/02-technical-deep-dive.png`
**Links:** https://github.com/amarjaleelbanbhan/CortexWard
**Hashtags:** #python #softwarearchitecture #appsec #machinelearning #opensource #securityengineering

---

The hardest part of "AI + security" isn't calling an LLM. It's making a confidence score you can actually trust — and stopping the model from lying to you.

Here's how CortexWard does it.

Every finding accumulates Evidence — a static match, a reachability proof, a taint trace, a sandboxed exploit. Each kind has a signed weight in log-odds space. Add them up, squash through a logistic function, and you get a calibrated confidence that's monotonic (more supporting evidence can only raise it) and explainable (you can point at exactly what moved the number).

Then two rules that make it a security tool instead of a demo:

1️⃣ LLM-insufficiency, enforced structurally. An LLM assessment is capped below the "verified" threshold and cannot advance the ladder. Not a prompt instruction — a property of the domain model. A model that hallucinates a vulnerability as "critical" simply can't push it past the ceiling.

2️⃣ Refutation is first-class. Evidence that something is *not* exploitable actively drives it toward NOT_AFFECTED, instead of being silently dropped.

The nice consequence: the confidence model is a ~100-line pure function. Deterministic. Property-testable. The same evidence always yields the same verdict — which is what makes the whole thing reproducible enough to benchmark.

It's all open — `cortexward.domain.verification` if you want to pick it apart (100% covered):
https://github.com/amarjaleelbanbhan/CortexWard

What would you weight differently? Genuinely asking.

#python #softwarearchitecture #appsec #machinelearning #opensource #securityengineering
