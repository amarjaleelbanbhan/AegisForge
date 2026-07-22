# Post 3 — Building Journey

**Purpose:** Relatable war-story; high engagement.
**When to post:** Fourth.
**Attach:** `docs/linkedin/assets/03-building-journey.png`
**Links:** https://github.com/amarjaleelbanbhan/CortexWard
**Hashtags:** #docker #devops #buildinpublic #opensource #softwareengineering #security

---

Three bugs in CortexWard's Docker sandbox that my dev machine *could not* have caught — every one surfaced only against a real Docker daemon in CI:

🐳 Docker refuses `docker cp` into a read-only container. My sandbox mounts the root filesystem read-only (it runs untrusted, LLM-generated exploit code — that's the point). So the "copy the PoC in, then run it" design was dead on arrival. Fix: *build* an ephemeral image with the bundle baked into a layer. No host mounts, ever.

🗑️ tmpfs is torn down the instant a container stops — before I could copy the produced artifacts back out. Retrieval came back empty every single time. Fix: a *named* Docker volume for /output, daemon-managed, independent of container lifecycle.

🔒 A fresh named volume is root-owned, so the unprivileged --user 1000:1000 container got Permission denied writing to it. Fix: chown the mount point at image-build time.

The lesson I keep relearning: infrastructure is never the ideal on paper. A real daemon behaves differently from the docs, and no amount of local mocking finds it. Each of these was one red CI run, one honest look at the stderr, one fix.

The upside of being strict about it: the sandbox now genuinely enforces --network none, read-only root, dropped capabilities, no-new-privileges, and hard timeouts — verified on real infrastructure, not asserted.

What's your favorite "only production could've told me that" bug?

https://github.com/amarjaleelbanbhan/CortexWard

#docker #devops #buildinpublic #opensource #softwareengineering #security
