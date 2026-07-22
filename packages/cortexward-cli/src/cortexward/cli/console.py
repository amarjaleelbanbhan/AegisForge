"""Centralized terminal styling for the `ward` CLI (Rich-based).

One place defines the whole visual system — semantic colors, severity styles,
status symbols, and the render helpers every command uses — so the CLI looks
consistent and no command hardcodes its own colors.

Design rules that keep it professional *and* robust:

- **stdout stays a clean machine contract.** Reports (SARIF/JSON/VEX) are the
  only thing written to stdout, so `ward scan . > out.sarif` and
  `ward scan . | jq` keep working byte-for-byte. Everything human — progress,
  panels, tables, summaries, errors — goes to **stderr**.
- **Decoration only in a real terminal.** `should_decorate()` is false when
  stderr isn't a TTY (pipes, CI, non-interactive), when `NO_COLOR` is set, or
  when `CORTEXWARD_NO_UI=1`. In those environments the CLI emits plain,
  unstyled text — no ANSI escapes, no spinners polluting logs.
- **Never color-only.** Every status carries a text/symbol indicator (``PASS``/
  ``FAIL``/``WARN`` + ✓/✗/!) that reads correctly in monochrome and for
  color-blind users. Symbols fall back to ASCII where the terminal can't encode
  Unicode (legacy Windows consoles).

Rich handles the cross-platform hard parts for us: Windows ANSI enabling,
`NO_COLOR`/`FORCE_COLOR`, light/dark-agnostic named colors, box-drawing
downgrade on legacy terminals, and width/wrapping.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from cortexward.domain import EvidenceKind, Finding, Severity

# --- Theme: semantic styles, not scattered raw colors -----------------------
# Named colors so the palette adapts across terminal themes; severities use the
# conventional red→cyan ramp. Every style pairs with a text label elsewhere, so
# meaning never rides on color alone.
_THEME = Theme(
    {
        "success": "bold green",
        "error": "bold red",
        "warning": "yellow",
        "info": "cyan",
        "muted": "dim",
        "heading": "bold white",
        "accent": "bold cyan",
        "sev.critical": "bold bright_red",
        "sev.high": "red",
        "sev.medium": "yellow",
        "sev.low": "cyan",
        "sev.info": "dim",
    }
)

# stderr for everything human; stdout is reserved for the machine report.
err_console = Console(stderr=True, theme=_THEME, highlight=False)
out_console = Console(theme=_THEME, highlight=False)


def _unicode_ok() -> bool:
    encoding = (getattr(sys.stderr, "encoding", None) or "").lower()
    return "utf" in encoding


# Status symbols with an ASCII fallback for terminals that can't encode them.
if _unicode_ok():
    SYMBOLS = {"ok": "✓", "fail": "✗", "warn": "!", "info": "•", "arrow": "→", "bullet": "·"}
else:  # pragma: no cover - exercised only on non-UTF terminals
    SYMBOLS = {"ok": "+", "fail": "x", "warn": "!", "info": "*", "arrow": "->", "bullet": "-"}


def should_decorate() -> bool:
    """Whether to emit styled, human-oriented output.

    False for pipes / CI / non-interactive stderr, when ``NO_COLOR`` is set, or
    when explicitly disabled via ``CORTEXWARD_NO_UI=1`` — so machine and log
    output stay clean.
    """
    if os.environ.get("CORTEXWARD_NO_UI") == "1":
        return False
    if "NO_COLOR" in os.environ:
        return False
    return err_console.is_terminal


# --- Severity presentation --------------------------------------------------

_SEVERITY_STYLE = {
    Severity.CRITICAL: "sev.critical",
    Severity.HIGH: "sev.high",
    Severity.MEDIUM: "sev.medium",
    Severity.LOW: "sev.low",
    Severity.INFO: "sev.info",
}


def severity_label(severity: Severity) -> str:
    """Uppercase, monochrome-safe severity label (never color-only)."""
    return severity.name


def severity_text(severity: Severity) -> Text:
    return Text(severity_label(severity), style=_SEVERITY_STYLE[severity])


# --- Render helpers (pure: take a Console, so they're testable in isolation) --


def render_error(
    console: Console, title: str, detail: str | None = None, hint: str | None = None
) -> None:
    """A structured, actionable error: what failed, why, and what to do next.

    Rendered to stderr as a bordered panel in a terminal, or plain ``error:``
    lines otherwise — always readable without color.
    """
    if not should_decorate():
        console.print(f"error: {title}", style="error")
        if detail:
            console.print(f"  {detail}")
        if hint:
            console.print(f"  hint: {hint}")
        return
    body = Text()
    body.append(title, style="error")
    if detail:
        body.append(f"\n\n{detail}", style="default")
    if hint:
        body.append(f"\n\n{SYMBOLS['arrow']} ", style="info")
        body.append(hint, style="info")
    console.print(Panel(body, title=f"{SYMBOLS['fail']} Error", border_style="error", expand=False))


def _location(finding: Finding) -> str:
    if not finding.locations:
        return "-"
    loc = finding.locations[0]
    return f"{loc.path}:{loc.start_line}"


def _has_poc(finding: Finding) -> bool:
    return any(ev.kind is EvidenceKind.EXPLOIT_POC and ev.supports for ev in finding.evidence)


def findings_table(findings: Sequence[Finding]) -> Table:
    """A findings table: severity · rule · location · state · evidence · message."""
    table = Table(box=None, pad_edge=False, expand=True, show_edge=False)
    table.add_column("severity", no_wrap=True)
    table.add_column("rule", style="muted", no_wrap=True)
    table.add_column("location", style="info", no_wrap=True)
    table.add_column("state", no_wrap=True)
    table.add_column("finding", overflow="fold")
    for finding in sorted(findings, key=lambda f: f.severity, reverse=True):
        state = finding.state.value
        if _has_poc(finding):
            state += f" {SYMBOLS['ok']}poc"
        table.add_row(
            severity_text(finding.severity),
            finding.rule_id,
            _location(finding),
            state,
            finding.message,
        )
    return table


def _severity_counts(findings: Sequence[Finding]) -> dict[Severity, int]:
    counts: dict[Severity, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def render_scan_header(
    console: Console,
    *,
    root: str,
    scanner_count: int,
    engine: str,
    sandbox: bool,
    llm: bool,
) -> None:
    """A compact header: what CortexWard is about to do, and with what."""
    pipeline = "static scanners"
    if llm:
        pipeline = f"agent pipeline ({engine})"
        if sandbox:
            pipeline += " + sandbox exploit verification"
    header = Text()
    header.append("CortexWard ", style="accent")
    header.append(f"scanning {root}\n", style="heading")
    header.append(
        f"{SYMBOLS['bullet']} {scanner_count} scanner(s) {SYMBOLS['bullet']} ", style="muted"
    )
    header.append(pipeline, style="muted")
    console.print(header)


def render_clean(console: Console, root: str) -> None:
    """The all-clear: a scan that found nothing to report."""
    if not should_decorate():
        console.print(f"ok: no findings in {root}")
        return
    body = Text()
    body.append(f"{SYMBOLS['ok']} No findings", style="success")
    body.append(f"\n\nNothing to report in {root}.", style="default")
    console.print(Panel(body, border_style="success", expand=False))


def render_next_steps(console: Console, *, has_findings: bool, machine_hint: str) -> None:
    """A short 'what now?' footer so the run doesn't end on a raw dump."""
    if not has_findings:
        return
    tip = Text()
    tip.append(f"{SYMBOLS['arrow']} ", style="info")
    tip.append("Next: ", style="info")
    tip.append(machine_hint, style="muted")
    console.print(tip)


def summary_line(findings: Sequence[Finding]) -> Text:
    """A one-line severity breakdown, e.g. ``2 critical · 1 high · 3 total``."""
    counts = _severity_counts(findings)
    text = Text()
    parts = [
        (sev, counts[sev])
        for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
        if counts.get(sev)
    ]
    for i, (sev, n) in enumerate(parts):
        if i:
            text.append(f" {SYMBOLS['bullet']} ", style="muted")
        text.append(f"{n} {sev.name.lower()}", style=_SEVERITY_STYLE[sev])
    if parts:
        text.append(f" {SYMBOLS['bullet']} ", style="muted")
    text.append(f"{len(findings)} total", style="muted")
    return text
