# Post 5 — Feature Spotlight: the closed exploit loop

**Purpose:** Show the single most impressive capability, concretely.
**When to post:** Second (right after Launch, while attention is fresh).
**Attach:** `docs/linkedin/assets/05-feature-spotlight.png`
**Optional second visual:** `docs/assets/demo-terminal.gif` (the real `ward scan` in action).
**Links:** https://github.com/amarjaleelbanbhan/CortexWard
**Hashtags:** #appsec #ai #security #python #opensource #devsecops #vulnerabilitymanagement

---

Most scanners tell you a line *might* be vulnerable. CortexWard tries to **prove it — and then prove the fix.**

Here's the loop, end to end, that just landed:

1. A scanner flags a command-injection finding.
2. The verifier weighs in (LLM) and the Code Property Graph proves the sink is reachable.
3. The PoC agent asks a model to write an exploit, then runs it in a locked-down Docker sandbox with a fresh, unguessable marker it must trigger *only* as a side effect of the vulnerable code.
4. Marker fires → EXPLOIT_POC evidence → the finding climbs to DYNAMIC_POC and becomes VERIFIED. (If it doesn't fire, nothing is claimed — a failed exploit never means "safe.")
5. A minimal patch is generated and put through four gates: it applies, existing tests pass, the rescan is clean, and — my favorite — Gate D re-runs the *exact same* exploit against the patched code. If that identical PoC no longer triggers, the fix is genuinely neutralizing, not just "the command exited zero."

Only when all four gates pass is a patch called validated.

The unguessable-marker detail matters: it's what stops a target's normal output — or a maliciously crafted one — from faking a successful exploit.

This is the difference between "AI thinks this is a bug" and "here's the exploit, here's the fix, and here's proof the fix kills the exploit."

Curious what people think of the four-gate approach — too strict, or exactly right for auto-generated patches?

https://github.com/amarjaleelbanbhan/CortexWard

#appsec #ai #security #python #opensource #devsecops #vulnerabilitymanagement
