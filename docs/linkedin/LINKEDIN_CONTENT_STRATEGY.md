# CortexWard — LinkedIn Content & Engagement Strategy

A simple, realistic plan to launch CortexWard on LinkedIn, attract developers, and convert attention
into feedback and contributions. Companion to `PROJECT_SHOWCASE.md` and `LINKEDIN_POSTS.md`.

---

## 1. Posting order & cadence

Post **one every 3–4 days** (not all at once — let each breathe and reply to comments). Best
windows for a dev audience: **Tue–Thu, ~9–11am** in your target timezone.

| Order | Post | Why this slot | Primary goal |
|------|------|---------------|--------------|
| 1️⃣ | **Launch** (Post 1) | Broadest hook; sets the "prove it, don't assert it" frame | Awareness + first stars |
| 2️⃣ | **Feature Spotlight** (Post 5) | Follow the launch with the single most impressive, concrete thing (the exploit loop) while attention is fresh | Credibility |
| 3️⃣ | **Technical Deep Dive** (Post 2) | Now that people are curious, earn the serious devs with the confidence model | Depth / trust |
| 4️⃣ | **Building Journey** (Post 3) | Human, relatable, high-engagement (war stories do well) | Reach + relatability |
| 5️⃣ | **Contribution** (Post 4) | Convert the audience you've built into contributors | Contributors / issues |

> Rationale: lead with the *idea*, immediately back it with a *concrete win*, then go deep, then get
> human, then ask for help. Asking for contributions first (before people are sold) converts poorly.

**After the 5:** keep momentum with lightweight follow-ups — a "first external contribution" shout-out,
a benchmark-number post once Milestone 2 lands, a short clip of a new feature.

---

## 2. Visual for each post (dev audiences scroll past text-only)

| Post | Visual to attach | Status |
|------|------------------|--------|
| 1 Launch | Terminal demo GIF | ✅ exists: `docs/assets/demo-terminal.gif` |
| 5 Spotlight | GIF of `ward scan --sandbox` reaching `DYNAMIC_POC` → `VERIFIED` | ⏳ `[TODO]` — record once Docker+Ollama are on one host (see `OWNER_ACTIONS.md`). Fallback: a clean before/after "finding state" diagram card |
| 2 Deep Dive | A card showing the ladder + log-odds formula, OR the hexagonal architecture diagram | `[TODO]` export a clean PNG |
| 3 Journey | Simple carousel: "3 bugs only a real Docker daemon could find" (1 slide per bug), OR a screenshot of the green CI matrix | `[TODO]` |
| 4 Contribution | The architecture diagram, OR a screenshot of the GitHub "good first issue" list | `[TODO]` create the labels first |

**Visuals to produce (priority order):**
1. **Architecture diagram PNG** — reuse the ASCII/hexagonal diagram from `PROJECT_SHOWCASE.md`; clean it up in Excalidraw/Mermaid and export at ~1200×675 (LinkedIn-friendly 16:9).
2. **Ladder + confidence card** — one slide: the 5 rungs + the log-odds one-liner + the "LLM can never verify" rule.
3. **PoC-loop GIF** — the money shot; record `ward scan --sandbox` end-to-end once the live loop runs.
4. **"3 bugs" carousel** — pull straight from Post 3.

Keep a consistent look: dark background, the 🛡️ shield, one accent color. Reuse `docs/assets/_gen_demo_gif.py` as the pattern for terminal recordings.

---

## 3. Turning attention into contributions

**Before you post the Contribution post (ideally before Post 1):**
- [ ] Create **`good first issue`** and **`help wanted`** labels on GitHub and tag 5–8 genuinely
      small, well-described issues (scanner adapter stub, a reporter, a docs page, widening PoC to
      one more CWE). Link them from `PROJECT_SHOWCASE.md` (`[TODO]` placeholder is there).
- [ ] Make sure `CONTRIBUTING.md` has a **10-minute happy path** (clone → `uv sync` → `ward scan .`).
      It mostly does — verify a fresh clone actually works end to end.
- [ ] Pin a **"Milestone 1: cross-file taint" tracking issue** — it's the flagship contribution and a
      great anchor for "where do I start?" replies.
- [ ] Add issue templates (there are already bug/feature templates in `.github/ISSUE_TEMPLATE/`).

**In the posts:** always end with a concrete, low-friction CTA — "star it," "tell me where it
breaks," "open an issue," "what would you weight differently?" Specific questions get replies;
"check it out" doesn't.

---

## 4. Engagement playbook (the first 48h matter most)

- **Reply to every comment within a few hours** on launch day — the algorithm rewards early
  engagement, and it's where real feedback lives.
- When someone raises a real critique or idea, **turn it into a GitHub issue** and reply "great point
  — opened #NN so it doesn't get lost." This (a) shows the project is alive, (b) converts a comment
  into tracked work, (c) gives that person a reason to come back.
- **Ask, don't broadcast.** Each post ends with a genuine question. Comments > likes for reach.
- **Cross-post** to r/netsec, r/Python, Hacker News ("Show HN"), and relevant Discord/Slack AppSec
  communities — but tailor the intro to each; don't paste the LinkedIn text verbatim.
- Keep a running note of feedback themes → fold the top 3 into the roadmap and mention it in a
  later post ("you asked for X, it's now on the roadmap / shipped"). That loop is what builds a
  community rather than an audience.

---

## 5. Guardrails (keep it credible)

- **Never overclaim.** It's pre-alpha with zero external users — say so. The honesty *is* the
  differentiator in a hype-saturated space.
- Don't claim the full live loop is "verified" until it's actually run on Docker+Ollama together —
  the showcase and posts already phrase this carefully. Keep it that way.
- No invented benchmarks. When Milestone 2 produces real false-positive-reduction numbers, *that's*
  the post that can go big — save the bold claims for when you have the data.
- Let the architecture and the "evidence over assertion" thesis carry it. That's real and rare.

---

## 6. Pre-publish checklist

- [ ] Replace every `[ADD LINK]` with the real GitHub URL (and demo/docs once they exist).
- [ ] Create `good first issue` labels + tag issues; update the link in `PROJECT_SHOWCASE.md`.
- [ ] Export the architecture-diagram PNG and the ladder/confidence card.
- [ ] Verify a **fresh clone** runs (`uv sync --all-packages --extra dev` → `uv run ward scan .`).
- [ ] Confirm the demo GIF still reflects current CLI output.
- [ ] (Optional, high-value) Record the `ward scan --sandbox` PoC-loop GIF once infra allows.
- [ ] Skim each post aloud once — cut anything that sounds like a press release.
