# cortexward-cli

The `ward` command-line interface for
[CortexWard](https://github.com/amarjaleelbanbhan/CortexWard) (MPS §8, Phase 8).

```
ward scan .                          # scan the current directory, SARIF to stdout
ward scan . -o results.sarif         # write SARIF to a file
ward scan . --language python        # restrict to specific languages
ward scan . --fail-on critical       # only exit non-zero on critical findings
```

Ships one command so far: `scan`, wiring together `cortexward-orchestrator`'s
`SequentialOrchestrator` (every auto-discovered scanner, correlated) and `cortexward-reporters`'s
`SarifReporter`. The REST API, GitHub App/Action, and VS Code extension are the rest of Phase 8.
