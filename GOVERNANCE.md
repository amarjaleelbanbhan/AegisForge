# CortexWard Governance

This document describes how decisions are made in the CortexWard project. It is intentionally
lightweight while the project is young and will evolve as the community grows.

## Principles

- **Transparency.** Technical decisions happen in the open — issues, pull requests, and design
  documents in the repository.
- **Meritocracy.** Influence is earned through sustained, high-quality contribution.
- **Research integrity.** Claims are backed by evidence and reproducible experiments.
- **Security first.** When in doubt, choose the option that is safer for users of the tool.

## Roles

- **Contributors** — anyone who submits issues, code, docs, or research. No formal status
  required.
- **Maintainers** — contributors with commit rights who review and merge changes, triage
  issues, and steward a subsystem. Maintainers are added by consensus of existing maintainers
  based on a track record of quality contributions and good judgment.
- **Steering Committee** — once the project is large enough, a small committee of maintainers
  responsible for cross-cutting direction, releases, and conflict resolution.

## Decision-making

- **Everyday changes** are decided by maintainer review on pull requests. Two maintainer
  approvals are preferred for changes to the domain core, security-sensitive paths, or public
  APIs; one approval suffices elsewhere.
- **Significant changes** (architecture, new subsystems, breaking APIs) are proposed as a
  design document or ADR and decided by **lazy consensus**: if no maintainer objects within a
  reasonable review window, the proposal is accepted. Objections are resolved by discussion,
  and, failing that, by a maintainer vote (simple majority; Steering Committee breaks ties).

## Adding maintainers

Any maintainer may nominate a contributor. Nominations are decided by consensus of the current
maintainers. New maintainers are expected to have demonstrated technical skill, sound
judgment, and alignment with the project's principles.

## Releases

Releases follow [Semantic Versioning](https://semver.org/). A maintainer prepares the release,
updates [CHANGELOG.md](CHANGELOG.md), and tags it once CI is green on `main`.

## Changing this document

Amendments to governance follow the "significant changes" process above.
