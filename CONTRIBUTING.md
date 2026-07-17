# Contributing to CortexWard

Thank you for your interest in CortexWard. This project aims to be a research-grade,
production-quality, community-driven security platform — contributions of code, tests,
documentation, benchmarks, and research ideas are all welcome.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Code** — new scanners, language front-ends, verifiers, or LLM backends (all plugin-based).
- **Research** — evaluation methods, datasets, or ideas (see [`research/`](research/)).
- **Docs** — tutorials, API reference, architecture notes.
- **Triage** — reproducing issues, improving tests, reviewing PRs.

Look for issues labeled **`good first issue`** to get started.

## Development setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). This is a **uv workspace**
([ADR-0005](docs/adr/0005-uv-workspace-monorepo.md)) — the root `pyproject.toml` is a virtual
manifest, so packages must be synced explicitly:

```bash
uv sync --all-packages --extra dev
```

Run the full quality gate locally before pushing — this is exactly what CI runs:

```bash
uv run ruff check packages                                  # lint
uv run ruff format packages                                 # format
for pkg in packages/*/; do uv run mypy "${pkg}src" "${pkg}tests"; done   # strict type check
uv run lint-imports                                          # hexagonal boundaries
uv run pytest --cov=cortexward --cov-fail-under=100          # tests + coverage gate
```

Mypy runs once per package rather than across the whole workspace: every package's `tests/` has
its own `conftest.py`, and since `tests/` directories intentionally have no `__init__.py` (so
one package's tests don't collide with a sibling's under the shared module name `tests` — see
the `--import-mode=importlib` note in `pyproject.toml`), a single combined mypy invocation would
see two same-named top-level `conftest` modules and refuse to proceed.

## Standards

- **Architecture:** respect the hexagonal boundaries — the domain core (`cortexward.domain`)
  and the port catalog (`cortexward.ports`) must stay pure (no I/O, no adapter imports); the
  plugin registry (`cortexward.plugins`) never imports a concrete adapter. New integrations are
  adapters implementing a port, registered via `PluginGroup` — see
  [ARCHITECTURE.md](ARCHITECTURE.md). `import-linter` enforces this mechanically in CI; a
  contract failure is a build failure, not a suggestion.
- **New packages:** a new subsystem (a scanner adapter, a language provider, ...) is a new
  member under `packages/<name>/` with its own `pyproject.toml`, added to the workspace by
  virtue of `[tool.uv.workspace] members = ["packages/*"]` — no root config changes needed
  beyond extending shared lint/type/test paths if the package needs its own.
- **Types:** all code is fully typed; `mypy --strict` must pass.
- **Tests:** every change ships with tests. The domain core is held at 100% coverage; use
  `hypothesis` for invariants where it fits. New ports ship a conformance test (a minimal
  in-memory fake proving the `Protocol` is satisfiable).
- **Security:** treat analyzed code as hostile input. Never add a path that lets a model or
  untrusted content bypass verification. Never commit secrets.
- **Style:** Ruff governs lint and formatting. Keep functions small and honest; match the
  surrounding code.

## Commit and branch conventions

- Work on feature branches: `feature/<topic>`, `fix/<topic>`, `docs/<topic>`.
- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat(scanner): …`,
  `fix(core): …`, `test(graph): …`, `docs(api): …`, `refactor(core): …`, `chore(ci): …`.
- Keep commits small and logical. Rebase before merge; keep `main` green.

## Pull requests

1. Ensure the local quality gate passes.
2. Update documentation and `CHANGELOG.md` when behavior changes.
3. Fill in the PR template, including the security checklist.
4. A maintainer reviews; merges happen only after CI is green.

## Reporting security issues

Do **not** open public issues for vulnerabilities — follow [SECURITY.md](SECURITY.md).
