# LinkedIn Content Kit

Everything needed to launch CortexWard on LinkedIn — captions, visuals, and a posting plan.
Grounded in the actual implementation; no invented features, metrics, or links.

## Start here

**[LINKEDIN_POSTING_DASHBOARD.md](LINKEDIN_POSTING_DASHBOARD.md)** — the copy-paste-and-post
sheet: for each post, which caption to copy, which image to attach, links, and hashtags.

## Contents

```
docs/linkedin/
├── README.md                      ← you are here
├── LINKEDIN_POSTING_DASHBOARD.md  ← copy caption, attach file, publish
├── PROJECT_SHOWCASE.md            ← full project source-of-truth for promotion
├── LINKEDIN_CONTENT_STRATEGY.md   ← cadence, engagement playbook, guardrails
├── posts/
│   ├── 01-project-launch.md
│   ├── 02-technical-deep-dive.md
│   ├── 03-building-journey.md
│   ├── 04-open-source-contribution.md
│   └── 05-feature-spotlight.md
└── assets/                        ← 1200×1200 PNGs, LinkedIn-ready
    ├── 01-project-launch.png
    ├── 02-technical-deep-dive.png
    ├── 03-building-journey.png
    ├── 04-open-source-contribution.png
    └── 05-feature-spotlight.png
```

The CLI demo animation lives at [`../assets/demo-terminal.gif`](../assets/demo-terminal.gif)
(the canonical copy used in the repo README) — attach it as an optional second visual on the
Feature Spotlight post. Regenerate it or the PNGs with:

```bash
uv run --with pillow python docs/assets/_gen_demo_gif.py     # the CLI demo GIF
uv run --with pillow python docs/linkedin/_gen_assets.py     # the 5 post PNGs
```

## Visual identity

All cards share one system: GitHub-dark background (`#0d1117`), the CortexWard shield + wordmark,
a cyan accent (`#39c5cf`), the CLI's own severity colors, and a repo-URL footer — 1200×1200 PNG,
which renders correctly on LinkedIn, GitHub, and social previews.
