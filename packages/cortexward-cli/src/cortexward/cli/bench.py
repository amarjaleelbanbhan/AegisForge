"""`ward bench run/compare/report` — the benchmark harness CLI (MPS §20.1/§23).

Closes the last open piece of Phase 3.5: `RunManifest`, the finding matcher,
and the statistical protocol (`cortexward-eval`) already existed; nothing
before this wired them into a runnable `ward bench` command. `bench run` is
deliberately the "Static-only" baseline MPS §3 itself names — every
registered `ScannerPort`, no LLM verification — matching `ward baseline`'s
own no-LLM-by-default design, so a benchmark run measures the scanners
themselves, not an LLM's influence on top of them.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess  # nosec B404
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from cortexward.eval import HardwareInfo, RunManifest, load_dataset, mcnemar_test, run_bench
from cortexward.orchestrator import SequentialOrchestrator, default_scanners
from cortexward.ports import AnalysisRequest

bench_app = typer.Typer(
    name="bench",
    help="The benchmark-first evaluation harness (MPS §23).",
    no_args_is_help=True,
)

_REPORT_FORMATS = ("md", "json")


def _git_sha() -> str:
    """This project's own commit (evaluation-framework.md §5), best-effort.

    A `ward` install from a built wheel (no `.git` present) or a missing
    `git` binary both degrade to `"unknown"` rather than failing the run —
    a benchmark result is still worth recording even without perfect
    provenance, the same "missing metadata doesn't block a result"
    tolerance `RunManifest`'s own optional fields already model.
    """
    git = "git"
    try:
        result = subprocess.run(  # noqa: S603 # nosec B603
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip()


def _hardware_info() -> HardwareInfo:
    cpu = platform.processor() or platform.machine() or "unknown"
    return HardwareInfo(cpu=cpu, os=platform.platform())


def _matches_path(manifest_path: Path) -> Path:
    """The companion per-example detection file `bench run` writes alongside a manifest.

    `RunManifest` itself only ever carries aggregate metrics (matching
    evaluation-framework.md §5's documented shape exactly) — this sidecar
    is what `bench compare` needs for McNemar's test (§6) on matched
    per-example outcomes, without inventing an undocumented extra field on
    the manifest's own audit-critical schema.
    """
    return manifest_path.with_suffix(manifest_path.suffix + ".matches.json")


@bench_app.command("run")
def bench_run(
    dataset_manifest: Annotated[
        Path,
        typer.Argument(help="Path to a dataset manifest.json.", exists=True, dir_okay=False),
    ],
    output: Annotated[Path, typer.Option("--output", "-o", help="RunManifest JSON to write.")],
) -> None:
    """Scans DATASET_MANIFEST's examples and writes a `RunManifest` to OUTPUT."""
    dataset = load_dataset(dataset_manifest)
    dataset_root = dataset_manifest.resolve().parent
    scanners = default_scanners()
    orchestrator = SequentialOrchestrator(scanners=scanners)

    started = datetime.now(UTC)
    start_perf = time.monotonic()
    result = orchestrator.run(AnalysisRequest(root=dataset_root))
    wall_seconds = time.monotonic() - start_perf

    config_hash = hashlib.sha256(
        ",".join(sorted(scanner.name for scanner in scanners)).encode("utf-8")
    ).hexdigest()[:16]

    manifest, per_example = run_bench(
        dataset,
        result.findings,
        run_id=f"bench_{uuid4().hex[:16]}",
        git_sha=_git_sha(),
        config_hash=config_hash,
        calibration_profile="static-default@1",
        started=started,
        wall_seconds=wall_seconds,
        hardware=_hardware_info(),
    )

    output.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _matches_path(output).write_text(
        json.dumps(dict(sorted(per_example.items())), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    typer.echo(
        f"Wrote RunManifest to {output} (precision={manifest.metrics.precision:.3f}, "
        f"recall={manifest.metrics.recall:.3f}, f1={manifest.metrics.f1:.3f})",
        err=True,
    )


@bench_app.command("compare")
def bench_compare(
    manifest_a: Annotated[
        Path, typer.Argument(help="First RunManifest JSON (baseline).", exists=True, dir_okay=False)
    ],
    manifest_b: Annotated[
        Path,
        typer.Argument(help="Second RunManifest JSON (candidate).", exists=True, dir_okay=False),
    ],
) -> None:
    """Reports metric deltas between two `ward bench run` outputs.

    Runs McNemar's test (evaluation-framework.md §6) on matched per-example
    detection outcomes when both runs' companion `.matches.json` sidecars
    (written by `bench run`) are present and share at least one example id;
    silently omitted otherwise rather than guessing at significance from
    aggregate metrics alone.
    """
    a = RunManifest.model_validate_json(manifest_a.read_text(encoding="utf-8"))
    b = RunManifest.model_validate_json(manifest_b.read_text(encoding="utf-8"))

    lines = [
        f"Run A: {a.run_id} ({a.dataset.name}@{a.dataset.version})",
        f"Run B: {b.run_id} ({b.dataset.name}@{b.dataset.version})",
        "",
        f"{'Metric':<10} {'A':>8} {'B':>8} {'Delta (B-A)':>12}",
    ]
    for field in ("precision", "recall", "f1", "fpr", "fnr"):
        value_a = getattr(a.metrics, field)
        value_b = getattr(b.metrics, field)
        lines.append(f"{field:<10} {value_a:>8.3f} {value_b:>8.3f} {value_b - value_a:>+12.3f}")

    matches_a_path, matches_b_path = _matches_path(manifest_a), _matches_path(manifest_b)
    if matches_a_path.exists() and matches_b_path.exists():
        matches_a = json.loads(matches_a_path.read_text(encoding="utf-8"))
        matches_b = json.loads(matches_b_path.read_text(encoding="utf-8"))
        shared_ids = sorted(set(matches_a) & set(matches_b))
        if shared_ids:
            only_a = sum(1 for eid in shared_ids if matches_a[eid] and not matches_b[eid])
            only_b = sum(1 for eid in shared_ids if matches_b[eid] and not matches_a[eid])
            result = mcnemar_test(only_a, only_b)
            lines.append("")
            lines.append(
                f"McNemar's test on {len(shared_ids)} shared example(s) "
                f"({result.discordant_pairs} discordant): "
                f"statistic={result.statistic:.3f}, p={result.p_value:.4f}"
            )

    typer.echo("\n".join(lines))


def _render_markdown(manifest: RunManifest) -> str:
    metrics = manifest.metrics
    lines = [
        f"# Benchmark report: {manifest.run_id}",
        "",
        f"- Dataset: {manifest.dataset.name}@{manifest.dataset.version}",
        f"- Git SHA: {manifest.git_sha}",
        f"- Calibration profile: {manifest.calibration_profile}",
        f"- Wall time: {manifest.runtime.wall_seconds:.2f}s",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Precision | {metrics.precision:.3f} |",
        f"| Recall | {metrics.recall:.3f} |",
        f"| F1 | {metrics.f1:.3f} |",
        f"| FPR | {metrics.fpr:.3f} |",
        f"| FNR | {metrics.fnr:.3f} |",
    ]
    return "\n".join(lines) + "\n"


def _render(manifest: RunManifest, report_format: str) -> str:
    if report_format == "json":
        return json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return _render_markdown(manifest)


@bench_app.command("report")
def bench_report(
    manifest_path: Annotated[
        Path, typer.Argument(help="RunManifest JSON to render.", exists=True, dir_okay=False)
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write to this file instead of stdout."),
    ] = None,
    report_format: Annotated[
        str, typer.Option("--format", help="Comma-separated: md, json.")
    ] = "md",
) -> None:
    """Renders a `RunManifest` as Markdown and/or JSON."""
    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    formats = [item.strip().lower() for item in report_format.split(",") if item.strip()]
    for fmt in formats:
        if fmt not in _REPORT_FORMATS:
            raise typer.BadParameter(
                f"invalid --format value {fmt!r}; expected one of: {', '.join(_REPORT_FORMATS)}"
            )

    if output is not None:
        for fmt in formats:
            target = output if len(formats) == 1 else output.with_suffix(f".{fmt}")
            target.write_text(_render(manifest, fmt), encoding="utf-8")
        typer.echo(f"Wrote report ({', '.join(formats)}) for run {manifest.run_id}", err=True)
    else:
        for fmt in formats:
            if len(formats) > 1:
                typer.echo(f"=== {fmt} ===")
            typer.echo(_render(manifest, fmt))


__all__ = ["bench_app"]
