# ADR-0005: uv workspace monorepo with `cortexward.*` namespace

**Status:** Accepted · **Date:** 2026-07-05 · **Changes Phase-1 layout**

## Context
Phase 1 shipped a single flat `cortexward` package. The 3–5 year system is a platform: core, CPG,
many language/scanner/LLM adapters, orchestrator, CLI, server, SDK, MCP, and third-party plugins —
with heavy, conflicting dependencies and different release cadences. One package forces one install
and one release, and prevents per-subsystem ownership.

## Decision
Restructure into a **uv workspace monorepo** of independently versioned packages using the
PEP 420 `cortexward.*` namespace: `cortexward-core`, `-cpg`, `-scanners`, `-llm`, `-orchestrator`,
`-sandbox`, `-storage`, `-eval`, `-cli`, `-server`, `-sdk`, under `packages/`. `cortexward-core`
holds the domain + ports and depends on nothing heavy. Imports (`from cortexward.domain import …`)
are unchanged.

## Consequences
- Slim core install; independent plugin release/versioning; per-package CI and ownership.
- The natural home for third-party plugin packages.
- Slightly more repo machinery (workspace config, per-package `pyproject.toml`).
- **Migration cost is low now** (~7 source files) and high after Phase 4 — hence do it in Phase 1.5.

## Alternatives considered
- **Keep one package with extras.** Rejected: cannot version/release plugins independently;
  dependency bloat in the core.
- **Multiple repos.** Rejected: cross-cutting changes and shared CI become painful early.

*Specified in [MPS §25](../specifications/MPS-v1.0.md#25-repository-structure).*
