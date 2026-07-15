"""The `ward` CLI entry point (MPS §8, Phase 8 — delivery surfaces).

Ships one command so far: `ward scan <path>`, wiring together everything
built in earlier phases (auto-discovered scanners → `SequentialOrchestrator`
→ cross-tool correlation → a `ReporterPort`) into an actual runnable tool,
rather than leaving those pieces as library-only building blocks. This is a
minimal, literal fulfillment of `ci.yml`'s own dogfood-job comment ("this
job is replaced once cortexward-scanners exists, at which point `ward scan
.` runs here") now that scanners and the orchestrator both exist.

`scan` also optionally drives the agent-driven pipeline
(`cortexward.agents.AgentOrchestrator`) instead of the plain scan-and-
correlate one, when an LLM provider is configured via `--llm-provider`/
`--llm-model` or `--llm-config`: findings then carry real LLM verification
and control-flow-reachability evidence, not just raw scanner output. With
no LLM flags given, `scan` behaves exactly as before — the agent pipeline is
opt-in, never a silent default, since it needs a real LLM backend
(local Ollama or a configured commercial provider) to be worth the extra
latency and cost.

The remaining Phase 8 surfaces (REST API, GitHub App, VS Code extension) are
unbuilt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from cortexward.agents import AgentOrchestrator, build_code_graphs, default_agents
from cortexward.domain import Severity
from cortexward.llm import LLMConfigError, LLMProviderConfig, Provider, build_llm, load_llm_config
from cortexward.orchestrator import SequentialOrchestrator, default_scanners
from cortexward.ports import AnalysisRequest, OrchestratorPort
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


def _build_orchestrator(
    *,
    llm_config: LLMProviderConfig | None,
    root: Path,
    languages: tuple[str, ...],
    reachability: bool,
) -> OrchestratorPort:
    scanners = default_scanners()
    if llm_config is None:
        return SequentialOrchestrator(scanners=scanners)
    llm = build_llm(llm_config)
    code_graphs = build_code_graphs(root, languages=languages) if reachability else None
    agents = default_agents(llm=llm, scanners=scanners, code_graphs=code_graphs)
    return AgentOrchestrator(agents)


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
) -> None:
    """Scan PATH with every registered scanner and report findings as SARIF."""
    threshold = _severity_threshold(fail_on)
    resolved_llm_config = _resolve_llm_config(
        llm_config=llm_config,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_api_key_env=llm_api_key_env,
        llm_base_url=llm_base_url,
    )

    resolved_root = path.resolve()
    orchestrator = _build_orchestrator(
        llm_config=resolved_llm_config,
        root=resolved_root,
        languages=tuple(language),
        reachability=reachability,
    )
    request = AnalysisRequest(root=resolved_root, languages=tuple(language))
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
