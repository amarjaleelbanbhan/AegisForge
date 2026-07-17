<!-- Thanks for contributing to CortexWard! Keep PRs small and focused. -->

## Summary

<!-- What does this change and why? Link related issues (e.g. "Closes #123"). -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Documentation
- [ ] Tests / CI
- [ ] Research

## Checklist

- [ ] The local quality gate passes: `ruff check`, `ruff format --check`, `mypy`, `pytest`.
- [ ] New/changed behavior is covered by tests.
- [ ] Documentation and `CHANGELOG.md` updated where relevant.
- [ ] The domain core (`cortexward.domain`) remains pure (no I/O / adapter imports).

## Security checklist

- [ ] No secrets, credentials, or tokens are committed.
- [ ] Analyzed/untrusted input is not treated as instructions and cannot bypass verification.
- [ ] Any new external/dangerous operation is isolated (sandbox, egress control) as appropriate.

## Notes for reviewers

<!-- Anything that needs special attention, trade-offs, or follow-ups. -->
