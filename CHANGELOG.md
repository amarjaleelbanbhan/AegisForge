# Changelog

All notable changes to AegisForge are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Phase 0 — Research & architecture.** Critical analysis of the research brief; adoption of
  the Verification Ladder and VEX/SARIF/SBOM outputs; hexagonal, in-process architecture.
  Design captured in `ARCHITECTURE.md`, `ROADMAP.md`, and `research/`.
- **Phase 1 — Foundation.**
  - `aegisforge` package with a pure, framework-free domain core: `Finding`, `Evidence`,
    `Provenance`, `SourceLocation`, `Patch`, and the `Assessment` value object.
  - The Verification Ladder calibration engine (`calibrate_confidence`, `assess`,
    `apply_assessment`) with log-odds evidence combination, the "LLM is never sufficient"
    policy, and refutation as first-class evidence.
  - Tooling: `uv`, Ruff (lint + format), `mypy --strict`, `pytest` + `hypothesis`; domain core
    at 100% coverage.
  - CI: lint · format · type · test matrix (Python 3.11–3.13) plus a self-audit job
    (`gitleaks`, `pip-audit`).
  - Open-source governance: `README`, `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`,
    `GOVERNANCE`, issue/PR templates, `Dockerfile`, and a devcontainer.

[Unreleased]: https://github.com/aegisforge/aegisforge/commits/main
