# Security Policy

CortexWard is a security tool, and we hold it to the standard it enforces on others. This
document covers how to report vulnerabilities and the security model of the project itself.

## Reporting a vulnerability

**Please do not open public issues for security vulnerabilities.**

Report privately via GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" on the Security tab), or email the maintainers at the address in the
repository metadata.

Please include:

- affected version / commit,
- a description and impact assessment,
- reproduction steps or a proof of concept,
- any suggested remediation.

We follow coordinated disclosure aligned with **ISO/IEC 29147**. We aim to acknowledge reports
within **3 business days** and to provide a remediation timeline within **10 business days**.
We will credit reporters who wish to be named once a fix is released.

## Supported versions

CortexWard is pre-1.0. Security fixes are applied to `main`. Once 1.0 ships, this table will
track supported release lines.

## Security model of CortexWard itself

CortexWard analyzes code that must be treated as **untrusted, adversarial input**. Our design
defends against, at minimum:

- **Prompt injection** embedded in source, comments, or documentation. Analyzed content is
  passed to models strictly as data; no tool exists that lets a model approve its own finding.
- **Code execution during analysis.** Static analysis never runs project build steps.
  Dynamic verification runs only inside a sandbox with deny-by-default egress.
- **Sandbox escape.** Progressive isolation tiers (container → microVM) and ephemeral
  environments between runs.
- **Secret handling.** Local-only operation is supported; when models are used, egress is
  explicit and secrets are redacted before any external call.
- **Supply chain.** The tool's own dependencies are minimal, pinned, and scanned in CI
  (`pip-audit`, `gitleaks`).

See [ARCHITECTURE.md](ARCHITECTURE.md) §5.1 for the full threat/defense matrix. A complete
STRIDE model is developed in Phase 5.

## Responsible use

CortexWard is for **authorized** security testing only. Do not run it against code you do not
own or lack permission to test. If it discovers previously unknown vulnerabilities in
third-party software, follow coordinated disclosure before publishing details.
