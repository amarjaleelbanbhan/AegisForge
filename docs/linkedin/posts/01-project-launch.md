# Post 1 — Project Launch

**Purpose:** Announce CortexWard; establish the "prove it, don't assert it" thesis.
**When to post:** First. Tue–Thu, ~9–11am.
**Attach:** `docs/linkedin/assets/01-project-launch.png`
**Links:** https://github.com/amarjaleelbanbhan/CortexWard
**Hashtags:** #opensource #appsec #cybersecurity #python #ai #devsecops #staticanalysis

---

Every "AI security scanner" I tried does the same thing: it bolts an LLM onto a linter and hands you a confident *"this is vulnerable."* No evidence. No way to check. Wrong often enough that people stop reading the output.

So I built the opposite.

**CortexWard** is an open-source autonomous AI security engineer with one rule baked into its core: **evidence decides, not the model.**

Instead of a yes/no, it climbs a Verification Ladder:

• pattern match →
• is the code even reachable? →
• does attacker-controlled data actually reach it? →
• can we generate a proof-of-concept and run it in a sandbox?

Only the last rung — an exploit that *actually fires* through the vulnerable path in an isolated Docker container — earns "verified." A language model can advise, but by construction it can never mark a finding verified on its own. That constraint is the whole point.

The output is standards-aligned VEX — the exploitability format regulators (EU CRA, CISA) are now asking for — grounded in verification instead of static guessing.

It's Python, Apache-2.0, hexagonal architecture, 100% test coverage, mypy-strict. Pre-alpha but real: `ward scan` runs a real multi-scanner + agent pipeline today.

⭐ If the "prove it, don't assert it" approach resonates, star it and tell me where it breaks:
https://github.com/amarjaleelbanbhan/CortexWard

#opensource #appsec #cybersecurity #python #ai #devsecops #staticanalysis
