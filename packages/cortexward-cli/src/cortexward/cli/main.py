"""The `ward` CLI entry point (MPS §8, Phase 8 — delivery surfaces).

Ships two commands: `ward scan <path>`, wiring together everything built in
earlier phases (auto-discovered scanners → `SequentialOrchestrator` →
cross-tool correlation → a `ReporterPort`) into an actual runnable tool,
rather than leaving those pieces as library-only building blocks; and `ward
serve`, running `cortexward-server`'s REST API (`cortexward.server.app`) via
`uvicorn`. `scan` is a minimal, literal fulfillment of `ci.yml`'s own
dogfood-job comment ("this job is replaced once cortexward-scanners exists,
at which point `ward scan .` runs here") now that scanners and the
orchestrator both exist.

`scan` also optionally drives the agent-driven pipeline
(`cortexward.agents.AgentOrchestrator`) instead of the plain scan-and-
correlate one, when an LLM provider is configured via `--llm-provider`/
`--llm-model` or `--llm-config`: findings then carry real LLM verification
and control-flow-reachability evidence, not just raw scanner output. With
no LLM flags given, `scan` behaves exactly as before — the agent pipeline is
opt-in, never a silent default, since it needs a real LLM backend
(local Ollama or a configured commercial provider) to be worth the extra
latency and cost.

The remaining Phase 8 surfaces (GitHub App, VS Code extension) are unbuilt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, cast

import typer
import uvicorn

from cortexward.cli import console as ui
from cortexward.cli.baseline import filter_baseline, load_baseline, write_baseline
from cortexward.cli.bench import bench_app
from cortexward.domain import Finding, Severity
from cortexward.llm import LLMConfigError, LLMProviderConfig, Provider, load_llm_config
from cortexward.orchestrator import (
    Engine,
    build_pipeline,
    build_threat_model_for,
    default_scanners,
)
from cortexward.plugins.groups import PluginGroup
from cortexward.plugins.registry import PluginNotFoundError, registry_for
from cortexward.ports import AnalysisRequest, ReporterPort

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


app.add_typer(bench_app, name="bench")


_FAIL_ON_CHOICES = ("none", "low", "medium", "high", "critical")
_ENGINE_CHOICES = ("agent", "langgraph")


def _resolve_engine(engine: str) -> Engine:
    if engine not in _ENGINE_CHOICES:
        raise typer.BadParameter(
            f"invalid --engine value {engine!r}; expected one of: {', '.join(_ENGINE_CHOICES)}"
        )
    return cast("Engine", engine)


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


def _resolve_llm_config(
    *,
    llm_config: Path | None,
    llm_provider: str | None,
    llm_model: str | None,
    llm_api_key: str | None,
    llm_api_key_env: str | None,
    llm_base_url: str | None,
) -> LLMProviderConfig | None:
    """Builds an `LLMProviderConfig` from CLI flags, or `None` for no LLM at all.

    `--llm-config` and `--llm-provider` are mutually exclusive ways to
    configure the same thing; neither given means the plain scan-and-
    correlate pipeline runs, exactly as if agent verification didn't exist.
    """
    if llm_config is not None and llm_provider is not None:
        raise typer.BadParameter("use either --llm-config or --llm-provider, not both")
    if llm_config is not None:
        try:
            return load_llm_config(llm_config)
        except LLMConfigError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if llm_provider is None:
        return None
    try:
        provider = Provider(llm_provider)
    except ValueError as exc:
        valid = ", ".join(p.value for p in Provider)
        raise typer.BadParameter(
            f"invalid --llm-provider value {llm_provider!r}; expected one of: {valid}"
        ) from exc
    if llm_model is None:
        raise typer.BadParameter("--llm-model is required when --llm-provider is set")
    return LLMProviderConfig(
        provider=provider,
        model=llm_model,
        api_key=llm_api_key,
        api_key_env=llm_api_key_env,
        base_url=llm_base_url,
    )


def _resolve_reporter(format_id: str) -> ReporterPort:
    """Loads the `ReporterPort` registered under `format_id` (e.g. `"sarif"`)."""
    try:
        return cast("ReporterPort", registry_for(PluginGroup.REPORTERS).create(format_id))
    except PluginNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _registered_scanner_count() -> int:
    """How many scanners the pipeline will run — for the scan header only."""
    return len(default_scanners())


def _echo_saved(message: str, output: Path) -> None:
    """Consistent 'wrote X to FILE' confirmation across commands (to stderr)."""
    if ui.should_decorate():
        ui.err_console.print(
            f"{ui.SYMBOLS['ok']} {message} {ui.SYMBOLS['arrow']} {output}", style="success"
        )
    else:
        typer.echo(f"{message}: {output}", err=True)


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(help="Root directory to scan.", exists=True, file_okay=False),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the report to this file instead of stdout."),
    ] = None,
    report_format: Annotated[
        str,
        typer.Option(
            "--format",
            help=(
                "Output format: 'auto' (default — human table in a terminal, SARIF when piped or "
                "saved), 'human', 'sarif', 'cortexward-json' (full evidence), or 'cyclonedx-vex'."
            ),
        ),
    ] = "auto",
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
    llm_provider: Annotated[
        str | None,
        typer.Option(
            "--llm-provider",
            help=(
                "Enable agent-driven LLM verification using this provider "
                "(e.g. 'ollama'). Omit to scan without LLM verification."
            ),
        ),
    ] = None,
    llm_model: Annotated[
        str | None,
        typer.Option("--llm-model", help="Model name for --llm-provider."),
    ] = None,
    llm_api_key: Annotated[
        str | None,
        typer.Option("--llm-api-key", help="Literal API key for --llm-provider."),
    ] = None,
    llm_api_key_env: Annotated[
        str | None,
        typer.Option(
            "--llm-api-key-env",
            help="Environment variable holding the API key for --llm-provider.",
        ),
    ] = None,
    llm_base_url: Annotated[
        str | None,
        typer.Option("--llm-base-url", help="Override the default base URL for --llm-provider."),
    ] = None,
    llm_config: Annotated[
        Path | None,
        typer.Option(
            "--llm-config",
            help="Load provider/model/API key from a YAML file instead of --llm-* flags.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    reachability: Annotated[
        bool,
        typer.Option(
            "--reachability/--no-reachability",
            help="With an LLM provider configured, also attach control-flow reachability evidence.",
        ),
    ] = True,
    engine: Annotated[
        str,
        typer.Option(
            "--engine",
            help=(
                "With an LLM provider configured, which OrchestratorPort runs the agent "
                f"sequence: {', '.join(_ENGINE_CHOICES)} (ADR-0002). "
                "Ignored without --llm-provider."
            ),
        ),
    ] = "agent",
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            help=(
                "Exclude findings listed in this baseline file (see `ward baseline`) from "
                "both the report and the --fail-on exit code."
            ),
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    sandbox: Annotated[
        bool,
        typer.Option(
            "--sandbox/--no-sandbox",
            help=(
                "With an LLM provider configured, dynamically verify exploitable findings by "
                "generating a proof-of-concept and running it in an isolated Docker sandbox "
                "(Verification Ladder rung DYNAMIC_POC). Requires a running Docker daemon; a "
                "PoC that can't run is treated as inconclusive, never a false 'safe'. Ignored "
                "without --llm-provider/--llm-config."
            ),
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress the human-readable summary; report only."),
    ] = False,
) -> None:
    """Scan PATH with every registered scanner and report findings.

    In a terminal, `ward scan` prints a readable findings table. When output is
    piped or written with `--output`, it emits SARIF (machine-readable) so
    `ward scan . > out.sarif` and `ward scan . | jq` keep working. Choose a
    format explicitly with `--format`.
    """
    threshold = _severity_threshold(fail_on)
    resolved = _resolve_output_format(report_format, output=output)
    resolved_llm_config = _resolve_llm_config(
        llm_config=llm_config,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_api_key_env=llm_api_key_env,
        llm_base_url=llm_base_url,
    )
    reporter = None if resolved == "human" else _resolve_reporter(resolved)

    resolved_root = path.resolve()
    decorate = ui.should_decorate() and not quiet
    if decorate:
        ui.render_scan_header(
            ui.err_console,
            root=str(resolved_root),
            scanner_count=_registered_scanner_count(),
            engine=engine,
            sandbox=sandbox,
            llm=resolved_llm_config is not None,
        )

    orchestrator = build_pipeline(
        llm_config=resolved_llm_config,
        root=resolved_root,
        languages=tuple(language),
        reachability=reachability,
        engine=_resolve_engine(engine),
        sandbox=sandbox,
    )
    request = AnalysisRequest(root=resolved_root, languages=tuple(language))
    if decorate:
        with ui.err_console.status("Analyzing...", spinner="dots"):
            result = orchestrator.run(request)
    else:
        result = orchestrator.run(request)

    findings: tuple[Finding, ...] = result.findings
    if baseline is not None:
        findings = tuple(filter_baseline(findings, load_baseline(baseline)))

    _emit_report(findings, reporter=reporter, output=output, decorate=decorate, root=resolved_root)

    if threshold is not None and any(finding.severity >= threshold for finding in findings):
        raise typer.Exit(code=1)


def _resolve_output_format(report_format: str, *, output: Path | None) -> str:
    """Resolve `--format auto` to a concrete format.

    `auto` renders the human table only when writing to an interactive terminal
    with no `--output`; otherwise it resolves to SARIF, so piping and file
    output stay machine-readable and unchanged.
    """
    valid = ("auto", "human", "sarif", "cortexward-json", "cyclonedx-vex")
    if report_format not in valid:
        raise typer.BadParameter(
            f"invalid --format value {report_format!r}; expected one of: {', '.join(valid)}"
        )
    if report_format != "auto":
        return report_format
    if output is None and sys.stdout.isatty():
        return "human"
    return "sarif"


def _emit_report(
    findings: tuple[Finding, ...],
    *,
    reporter: ReporterPort | None,
    output: Path | None,
    decorate: bool,
    root: Path,
) -> None:
    """Write the machine report (or render the human table), plus a terminal summary."""
    if reporter is None:  # human format -> render the table to stdout
        if not findings:
            ui.render_clean(ui.out_console, str(root))
            return
        ui.out_console.print(ui.findings_table(findings))
        ui.out_console.print(ui.summary_line(findings))
        ui.render_next_steps(
            ui.out_console,
            has_findings=True,
            machine_hint="`--format cortexward-json` for full evidence, `--output` to save SARIF.",
        )
        return

    artifact = reporter.render(findings)
    if output is not None:
        output.write_bytes(artifact.content)
    else:
        sys.stdout.buffer.write(artifact.content)
    if decorate:  # a short human summary alongside the machine report
        if findings:
            ui.err_console.print(ui.summary_line(findings))
        if output is not None:
            ui.err_console.print(
                f"{ui.SYMBOLS['ok']} Wrote {len(findings)} finding(s) to {output}", style="success"
            )


@app.command("baseline")
def generate_baseline(
    path: Annotated[
        Path,
        typer.Argument(help="Root directory to scan.", exists=True, file_okay=False),
    ] = Path("."),
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Baseline file to write."),
    ] = Path("cortexward-baseline.json"),
    language: Annotated[
        list[str],
        typer.Option("--language", "-l", help="Restrict scanning to these languages (repeatable)."),
    ] = [],  # noqa: B006 - typer treats this as an immutable per-invocation default
    reason: Annotated[
        str,
        typer.Option("--reason", help="Recorded on every suppression entry, for reviewers."),
    ] = "accepted at baseline generation time",
) -> None:
    """Record every current scanner finding under PATH as accepted, in OUTPUT.

    Deliberately scanner-only, with no LLM verification: a baseline records
    what the plain scanners find today, not an LLM-influenced verification
    outcome. Re-run this after fixing or accepting new findings to update it.
    """
    resolved_root = path.resolve()
    orchestrator = build_pipeline(llm_config=None, root=resolved_root, languages=tuple(language))
    request = AnalysisRequest(root=resolved_root, languages=tuple(language))
    if ui.should_decorate():
        with ui.err_console.status("Scanning for a baseline...", spinner="dots"):
            result = orchestrator.run(request)
    else:
        result = orchestrator.run(request)

    write_baseline(output, result.findings, reason=reason)
    _echo_saved(f"{len(result.findings)} finding(s) recorded in baseline", output)


@app.command("threat-model")
def threat_model(
    path: Annotated[
        Path,
        typer.Argument(help="Root directory to scan.", exists=True, file_okay=False),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Write the threat model to this file instead of stdout."
        ),
    ] = None,
    language: Annotated[
        list[str],
        typer.Option("--language", "-l", help="Restrict scanning to these languages (repeatable)."),
    ] = [],  # noqa: B006 - typer treats this as an immutable per-invocation default
    reachability: Annotated[
        bool,
        typer.Option(
            "--reachability/--no-reachability",
            help=(
                "Attach CPG-grounded entry-point reachability and trust-boundary-crossing "
                "proofs to each threat."
            ),
        ),
    ] = True,
) -> None:
    """Build a STRIDE threat model from PATH's scanner findings (MPS Phase 5).

    Deliberately scanner-only, with no LLM verification: STRIDE
    classification and reachability are both deterministic (see
    `cortexward.agents.threat_model`), so this never needs an LLM backend.
    """
    resolved_root = path.resolve()
    model = build_threat_model_for(
        root=resolved_root, languages=tuple(language), reachability=reachability
    )
    content = (
        json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    if output is not None:
        output.write_bytes(content)
        _echo_saved(f"{len(model.threats)} threat(s) written", output)
    else:
        sys.stdout.buffer.write(content)


@app.command()
def serve(
    host: Annotated[
        str, typer.Option("--host", help="Bind address for the REST API.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port for the REST API.")] = 8000,
    reload: Annotated[
        bool, typer.Option("--reload", help="Auto-reload on source changes (development only).")
    ] = False,
) -> None:
    """Run the CortexWard REST API (see `cortexward-server`; MPS §20.2).

    A single-tenant, trusted-caller tool: no authentication, no
    rate-limiting, and `POST /v1/scans` accepts any filesystem path
    reachable from this process. Do not bind `--host 0.0.0.0` on a
    network you don't fully trust.
    """
    if ui.should_decorate():
        ui.err_console.print(
            f"{ui.SYMBOLS['arrow']} CortexWard API on [accent]http://{host}:{port}[/accent]  "
            "[muted](Ctrl+C to stop)[/muted]"
        )
    uvicorn.run("cortexward.server.app:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
