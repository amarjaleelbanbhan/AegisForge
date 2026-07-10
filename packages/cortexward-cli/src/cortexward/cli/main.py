"""The `ward` CLI entry point (MPS §8, Phase 8 — delivery surfaces).

Ships one command so far: `ward scan <path>`, wiring together everything
built in earlier phases (auto-discovered scanners → `SequentialOrchestrator`
→ cross-tool correlation → a `ReporterPort`) into an actual runnable tool,
rather than leaving those pieces as library-only building blocks. This is a
minimal, literal fulfillment of `ci.yml`'s own dogfood-job comment ("this
job is replaced once cortexward-scanners exists, at which point `ward scan
.` runs here") now that scanners and the orchestrator both exist. The
remaining Phase 8 surfaces (REST API, GitHub App, VS Code extension) are
unbuilt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from cortexward.domain import Severity
from cortexward.orchestrator import SequentialOrchestrator, default_scanners
from cortexward.ports import AnalysisRequest
from cortexward.reporters import SarifReporter

app = typer.Typer(
    name="ward",
    help="CortexWard: an autonomous AI software security engineer.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _callback() -> None:
    """CortexWard: an autonomous AI software security engineer.

    An explicit callback (even an empty one) keeps `scan` addressable as
    `ward scan ...` rather than Typer collapsing a single-command app so
    its one command can be invoked without naming it — this app is
    expected to grow more subcommands as later phases land.
    """


_FAIL_ON_CHOICES = ("none", "low", "medium", "high", "critical")


def _severity_threshold(fail_on: str) -> Severity | None:
    normalized = fail_on.strip().lower()
    if normalized == "none":
        return None
    try:
        return Severity[normalized.upper()]
    except KeyError as exc:
        raise typer.BadParameter(
            f"invalid --fail-on value {fail_on!r}; expected one of: {', '.join(_FAIL_ON_CHOICES)}"
        ) from exc


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(help="Root directory to scan.", exists=True, file_okay=False),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Write the SARIF report to this file instead of stdout."
        ),
    ] = None,
    language: Annotated[
        list[str],
        typer.Option("--language", "-l", help="Restrict scanning to these languages (repeatable)."),
    ] = [],  # noqa: B006 - typer treats this as an immutable per-invocation default
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help=f"Minimum severity that causes a non-zero exit: {', '.join(_FAIL_ON_CHOICES)}.",
        ),
    ] = "high",
) -> None:
    """Scan PATH with every registered scanner and report findings as SARIF."""
    threshold = _severity_threshold(fail_on)

    orchestrator = SequentialOrchestrator(scanners=default_scanners())
    request = AnalysisRequest(root=path.resolve(), languages=tuple(language))
    result = orchestrator.run(request)

    artifact = SarifReporter().render(result.findings)
    if output is not None:
        output.write_bytes(artifact.content)
        typer.echo(f"Wrote {len(result.findings)} finding(s) to {output}", err=True)
    else:
        sys.stdout.buffer.write(artifact.content)

    if threshold is not None and any(finding.severity >= threshold for finding in result.findings):
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
