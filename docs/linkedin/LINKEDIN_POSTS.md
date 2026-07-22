# CortexWard — LinkedIn Posts

Five ready-to-post drafts, grounded in the real project. Written to sound like the developer who
built it — not a marketing bot. Swap `[ADD LINK]` for the real URLs before posting, and attach the
suggested visual (see `LINKEDIN_CONTENT_STRATEGY.md`).

Repo: https://github.com/amarjaleelbanbhan/CortexWard

---

## Post 1 — Project Launch  🚀

> **Visual:** the terminal demo GIF (`docs/assets/demo-terminal.gif`).

---

Every "AI security scanner" I've tried does the same thing: it bolts an LLM onto a linter and hands
you a confident *"this is vulnerable."* No evidence. No way to check. Wrong often enough that people
stop reading the output.

So I built the opposite.

**CortexWard** is an open-source autonomous AI security engineer with one rule baked into its core:
**evidence decides, not the model.**

Instead of a yes/no, it climbs a Verification Ladder:

• pattern match →
• is the code even reachable? →
• does attacker-controlled data actually reach it? →
• **can we generate a proof-of-concept and run it in a sandbox?**

Only the last rung — an exploit that *actually fires* through the vulnerable path in an isolated
Docker container — earns "verified." A language model can advise, but by construction it can never
mark a finding verified on its own. That constraint is the whole point.

The output is standards-aligned VEX — the exploitability format regulators (EU CRA, CISA) are now
asking for — grounded in verification instead of static guessing.

It's Python, Apache-2.0, hexagonal architecture, 100% test coverage, mypy-strict. Pre-alpha but
real: `ward scan` runs a real multi-scanner + agent pipeline today.

⭐ If the "prove it, don't assert it" approach to AI security resonates, star it and tell me where
it breaks: [ADD LINK: github.com/amarjaleelbanbhan/CortexWard]

#opensource #appsec #cybersecurity #python #ai #devsecops #staticanalysis

---

## Post 2 — Technical Deep Dive  🔬

> **Visual:** a code/diagram card of the ladder + the log-odds formula, or the architecture diagram.

---

The hardest part of "AI + security" isn't calling an LLM. It's making a confidence score you can
actually trust — and stopping the model from lying to you.

Here's how CortexWard does it.

Every finding accumulates **Evidence** — a static match, a reachability proof, a taint trace, a
sandboxed exploit. Each kind has a signed weight in **log-odds space**. Add them up, squash through
a logistic function, and you get a calibrated confidence that's **monotonic** (more supporting
evidence can only raise it) and **explainable** (you can point at exactly what moved the number).

Then two rules that make it a security tool instead of a demo:

1️⃣ **LLM-insufficiency, enforced structurally.** An `LLM_ASSESSMENT` is capped below the "verified"
threshold and cannot advance the ladder. Not a prompt instruction — a property of the domain model.
An LLM that hallucinates a vulnerability as "critical" simply can't push it past the ceiling.

2️⃣ **Refutation is first-class.** Evidence that something is *not* exploitable actively drives it
toward `NOT_AFFECTED`, instead of being silently dropped.

The nice consequence: the confidence model is a ~100-line pure function. Deterministic. Property-
testable. The same evidence always yields the same verdict — which is what makes the whole thing
reproducible enough to benchmark.

Full module is `cortexward.domain.verification` if you want to pick it apart (100% covered):
[ADD LINK]

What would you weight differently? Genuinely asking.

#python #softwarearchitecture #appsec #machinelearning #opensource #securityengineering

---

## Post 3 — Building Journey  🛠️

> **Visual:** a "3 bugs only a real daemon could find" carousel, or a screenshot of the CI matrix.

---

Three bugs in CortexWard's Docker sandbox that my dev machine *could not* have caught — every one
surfaced only against a real Docker daemon in CI:

🐳 **Docker refuses `docker cp` into a read-only container.** My sandbox mounts the root filesystem
read-only (it runs untrusted, LLM-generated exploit code — that's the point). So the "copy the PoC
in, then run it" design was dead on arrival. Fix: *build* an ephemeral image with the bundle baked
into a layer. No host mounts, ever.

🗑️ **tmpfs is torn down the instant a container stops** — before I could copy the produced artifacts
back out. Retrieval came back empty every single time. Fix: a *named* Docker volume for `/output`,
daemon-managed, independent of container lifecycle.

🔒 **A fresh named volume is root-owned**, so the unprivileged `--user 1000:1000` container got
Permission denied writing to it. Fix: `chown` the mount point at image-build time.

The lesson I keep relearning: **hardware and infrastructure are never the ideal on paper.** A real
daemon behaves differently from the docs, and no amount of local mocking finds it. Each of these was
one red CI run, one honest look at the stderr, one fix.

The upside of being strict about it: the sandbox now genuinely enforces `--network none`, read-only
root, dropped capabilities, no-new-privileges, and hard timeouts — verified on real infrastructure,
not asserted.

What's your favorite "only production could've told me that" bug?

[ADD LINK]

#docker #devops #buildinpublic #opensource #softwareengineering #security

---

## Post 4 — Open Source / Contribution  🤝

> **Visual:** the architecture diagram, or a screenshot of the "good first issue" list.

---

I've been building CortexWard — an open-source AI security engineer — mostly solo, and it's at the
point where it genuinely benefits from more eyes and hands.

It's designed to be extended without touching the core. Most capabilities are **plugin adapters**
discovered via entry points, behind clean `typing.Protocol` ports. The dependency direction is
enforced by `import-linter`, so it's hard to make a mess even if you try.

Concretely, here's where you could jump in:

🧩 **Add a scanner** — implement `ScannerPort`, register it, done. Your findings flow into the same
correlation + verification pipeline.
🤖 **Live-test an LLM adapter** — the Anthropic/Gemini adapters are unit-tested but not yet verified
against a real key.
🕸️ **The big one — cross-file taint.** Today the Code Property Graph resolves calls within a file.
Inter-module resolution + inter-procedural taint is the single highest-impact feature for real
Flask/Django codebases. Meaty, well-scoped, genuinely interesting.
📄 **New reporters, docs, examples, a getting-started guide.**

It's Apache-2.0, Python 3.11+, 100% coverage, and the contributing guide + governance are already
written.

If you care about AppSec, program analysis, or just want a well-architected Python codebase to hack
on: clone it, break it, open an issue, tell me what's confusing. Feedback is as valuable as code
right now.

⭐ [ADD LINK: github.com/amarjaleelbanbhan/CortexWard]

#opensource #python #contributing #appsec #hacktoberfest #devsecops #programanalysis

---

## Post 5 — Feature Spotlight: the closed exploit loop  🎯

> **Visual:** a GIF of `ward scan --sandbox` reaching DYNAMIC_POC → VERIFIED [TODO: record], or a
> before/after "finding state" diagram.

---

Most scanners tell you a line *might* be vulnerable. CortexWard tries to **prove it — and then prove
the fix.**

Here's the loop, end to end, that just landed:

1. A scanner flags a command-injection finding.
2. The verifier weighs in (LLM) and the Code Property Graph proves the sink is reachable.
3. **The PoC agent asks a model to write an exploit**, then runs it in a locked-down Docker sandbox
   with a fresh, unguessable marker it must trigger *only* as a side effect of the vulnerable code.
4. Marker fires → `EXPLOIT_POC` evidence → the finding climbs to **`DYNAMIC_POC`** and becomes
   **`VERIFIED`**. (If it doesn't fire, nothing is claimed — a failed exploit never means "safe.")
5. A minimal patch is generated and put through **four gates**: it applies, existing tests pass, the
   rescan is clean, and — my favorite — **Gate D re-runs the *exact same* exploit against the patched
   code.** If that identical PoC no longer triggers, the fix is genuinely neutralizing, not just
   "the command exited zero."

Only when all four gates pass is a patch called validated.

The unguessable-marker detail matters: it's what stops a target's normal output — or a maliciously
crafted one — from faking a successful exploit.

This is the difference between "AI thinks this is a bug" and "here's the exploit, here's the fix, and
here's proof the fix kills the exploit."

Curious what people think of the four-gate approach — too strict, or exactly right for auto-generated
patches? [ADD LINK]

#appsec #ai #security #python #opensource #devsecops #vulnerabilitymanagement
