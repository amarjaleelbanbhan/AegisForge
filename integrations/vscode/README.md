# CortexWard for VS Code

Runs [CortexWard](https://github.com/amarjaleelbanbhan/CortexWard)'s `ward scan` against the
open workspace and shows findings as inline diagnostics (squiggles + Problems panel), instead
of reading a SARIF file by hand.

## Requirements

The `ward` CLI (`cortexward-cli`) must already be installed and on `PATH`, or its path
configured via `cortexward.wardPath`. This extension only shells out to it — it does not bundle
or install CortexWard itself.

```bash
uv sync --all-packages --extra dev   # from a CortexWard checkout
# or, once published: pip install cortexward-cli
```

## Usage

Run **CortexWard: Scan Workspace** from the Command Palette. Findings appear as diagnostics on
the affected files (severity mapped from SARIF: `error` → Error, `warning` → Warning, `note` →
Information); a summary is shown once the scan completes. Run **CortexWard: Clear Findings** to
clear them.

## Settings

| Setting | Default | Description |
|---|---|---|
| `cortexward.wardPath` | `"ward"` | Path to the `ward` executable. Defaults to resolving `ward` from `PATH`. |

## What this deliberately doesn't do (yet)

- No file-save-triggered auto-scan (`scanWorkspace` is manual, on demand) — a full `ward scan`
  isn't fast enough to run on every keystroke/save without an incremental mode this project
  doesn't have yet.
- No LLM-driven verification (`--llm-provider`) — the extension always runs the plain
  scanner-only pipeline (`--fail-on none --format sarif`), matching `ward baseline`'s and `ward
  threat-model`'s own "no LLM by default" design.
- No quick-fix / code actions — findings are read-only diagnostics; use `ward`'s own patch
  pipeline (Phase 7) for automated fixes.

## Development

```bash
cd integrations/vscode
npm install
npm run compile
npm run test:unit          # pure logic, no VS Code needed
npm run test:integration   # launches a real VS Code Extension Host
```

Press `F5` in VS Code (with this directory open) to launch an Extension Development Host for
manual testing.

## License

Apache-2.0, matching the rest of the CortexWard monorepo.
