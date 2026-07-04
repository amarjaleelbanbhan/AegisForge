# Contributing to AegisForge

Thank you for your interest in AegisForge. This project aims to be a research-grade,
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

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv venv
uv pip install -e ".[dev]"
```

Run the full quality gate locally before pushing — this is exactly what CI runs:

```bash
uv run ruff check src tests          # lint
uv run ruff format src tests         # format
uv run mypy                          # strict type check
uv run pytest --cov=aegisforge       # tests + coverage
```

## Standards

- **Architecture:** respect the hexagonal boundaries — the domain core (`aegisforge.domain`)
  must stay pure (no I/O, no framework or adapter imports). New integrations are adapters
  behind ports. See [ARCHITECTURE.md](ARCHITECTURE.md).
- **Types:** all code is fully typed; `mypy --strict` must pass.
- **Tests:** every change ships with tests. The domain core is held at 100% coverage; use
  `hypothesis` for invariants where it fits.
- **Security:** treat analyzed code as hostile input. Never add a path that lets a model or
  untrusted content bypass verification. Never commit secrets.
- **Style:** Ruff governs lint and formatting. Keep functions small and honest; match the
  surrounding code.

## Commit and branch conventions

- Work on feature branches: `feature/<topic>`, `fix/<topic>`, `docs/<topic>`.
- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat(scanner): …`,
  `fix(core): …`, `test(graph): …`, `docs(api): …`, `refactor(core): …`, `chore(ci): …`.
- Keep commits small and logical. Rebautify before merge; keep `main` green.

## Pull requests

1. Ensure the local quality gate passes.
2. Update documentation and `CHANGELOG.md` when behavior changes.
3. Fill in the PR template, including the security checklist.
4. A maintainer reviews; merges happen only after CI is green.

## Reporting security issues

Do **not** open public issues for vulnerabilities — follow [SECURITY.md](SECURITY.md).
