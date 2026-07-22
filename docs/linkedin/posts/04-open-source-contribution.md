# Post 4 — Open-Source / Contribution

**Purpose:** Convert the audience into contributors.
**When to post:** Fifth (last of the core five).
**Attach:** `docs/linkedin/assets/04-open-source-contribution.png`
**Links:** https://github.com/amarjaleelbanbhan/CortexWard
**Hashtags:** #opensource #python #contributing #appsec #devsecops #programanalysis

---

I've been building CortexWard — an open-source AI security engineer — mostly solo, and it's at the point where it genuinely benefits from more eyes and hands.

It's designed to be extended without touching the core. Most capabilities are plugin adapters discovered via entry points, behind clean typing.Protocol ports. The dependency direction is enforced by import-linter, so it's hard to make a mess even if you try.

Concretely, here's where you could jump in:

🧩 Add a scanner — implement ScannerPort, register it, done. Your findings flow into the same correlation + verification pipeline.
🤖 Live-test an LLM adapter — the Anthropic/Gemini adapters are unit-tested but not yet verified against a real key.
🕸️ The big one — cross-file taint. Today the Code Property Graph resolves calls within a file. Inter-module resolution + inter-procedural taint is the single highest-impact feature for real Flask/Django codebases. Meaty, well-scoped, genuinely interesting.
📄 New reporters, docs, examples, a getting-started guide.

It's Apache-2.0, Python 3.11+, 100% coverage, and the contributing guide + governance are already written.

If you care about AppSec, program analysis, or just want a well-architected Python codebase to hack on: clone it, break it, open an issue, tell me what's confusing. Feedback is as valuable as code right now.

⭐ https://github.com/amarjaleelbanbhan/CortexWard

#opensource #python #contributing #appsec #devsecops #programanalysis
