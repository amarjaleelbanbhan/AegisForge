"""Unit tests for the CLI styling/console module.

Render helpers are pure (they take a `Console`), so we render into an in-memory
buffer with `force_terminal=True` and assert on the text — no real TTY needed.
`should_decorate()` is monkeypatched to exercise both the styled and the plain
(pipe/CI/NO_COLOR) code paths.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from cortexward.cli import console as ui
from cortexward.domain import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingState,
    Provenance,
    Severity,
    SourceLocation,
    VerificationRung,
)

pytestmark = pytest.mark.unit


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=100, theme=ui._THEME, highlight=False)
    return console, buffer


def _finding(
    *,
    severity: Severity = Severity.HIGH,
    rule_id: str = "B602",
    with_location: bool = True,
    with_poc: bool = False,
    state: FindingState = FindingState.CANDIDATE,
) -> Finding:
    evidence: tuple[Evidence, ...] = ()
    if with_poc:
        evidence = (
            Evidence(
                kind=EvidenceKind.EXPLOIT_POC,
                rung=VerificationRung.DYNAMIC_POC,
                supports=True,
                summary="poc",
                provenance=Provenance(producer="poc"),
            ),
        )
    return Finding(
        rule_id=rule_id,
        title="t",
        message="subprocess with shell=True",
        cwe=78,
        severity=severity,
        locations=(SourceLocation(path="app.py", start_line=5),) if with_location else (),
        evidence=evidence,
        state=state,
        provenance=Provenance(producer="bandit"),
    )


class TestShouldDecorate:
    def test_no_color_env_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        assert ui.should_decorate() is False

    def test_explicit_no_ui_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("CORTEXWARD_NO_UI", "1")
        assert ui.should_decorate() is False

    def test_terminal_enables_when_no_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("CORTEXWARD_NO_UI", raising=False)
        monkeypatch.setattr(ui, "err_console", Console(force_terminal=True))
        assert ui.should_decorate() is True

    def test_non_terminal_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("CORTEXWARD_NO_UI", raising=False)
        monkeypatch.setattr(ui, "err_console", Console(file=io.StringIO(), force_terminal=False))
        assert ui.should_decorate() is False


class TestSeverity:
    @pytest.mark.parametrize("severity", list(Severity))
    def test_label_is_the_uppercase_name(self, severity: Severity) -> None:
        assert ui.severity_label(severity) == severity.name

    @pytest.mark.parametrize("severity", list(Severity))
    def test_severity_text_carries_the_label(self, severity: Severity) -> None:
        assert ui.severity_text(severity).plain == severity.name


class TestFindingsTable:
    def test_renders_all_columns(self) -> None:
        console, buffer = _console()
        console.print(ui.findings_table([_finding()]))
        out = buffer.getvalue()
        assert "HIGH" in out
        assert "B602" in out
        assert "app.py:5" in out
        assert "candidate" in out

    def test_poc_evidence_is_flagged_in_state(self) -> None:
        console, buffer = _console()
        console.print(ui.findings_table([_finding(with_poc=True, state=FindingState.VERIFIED)]))
        assert "poc" in buffer.getvalue()

    def test_missing_location_renders_dash(self) -> None:
        console, buffer = _console()
        console.print(ui.findings_table([_finding(with_location=False)]))
        assert "-" in buffer.getvalue()

    def test_sorted_by_severity_descending(self) -> None:
        console, buffer = _console()
        table = ui.findings_table(
            [
                _finding(severity=Severity.LOW, rule_id="LOW1"),
                _finding(severity=Severity.CRITICAL, rule_id="CRIT1"),
            ]
        )
        console.print(table)
        out = buffer.getvalue()
        assert out.index("CRIT1") < out.index("LOW1")


class TestSummaryLine:
    def test_counts_by_severity(self) -> None:
        text = ui.summary_line(
            [
                _finding(severity=Severity.CRITICAL),
                _finding(severity=Severity.HIGH),
                _finding(severity=Severity.HIGH),
            ]
        )
        plain = text.plain
        assert "1 critical" in plain
        assert "2 high" in plain
        assert "3 total" in plain

    def test_empty_findings_is_just_total(self) -> None:
        assert ui.summary_line([]).plain == "0 total"


class TestRenderError:
    def test_decorated_panel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ui, "should_decorate", lambda: True)
        console, buffer = _console()
        ui.render_error(
            console, "Docker not found", detail="daemon unreachable", hint="start Docker"
        )
        out = buffer.getvalue()
        assert "Docker not found" in out
        assert "daemon unreachable" in out
        assert "start Docker" in out

    def test_plain_when_not_decorated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ui, "should_decorate", lambda: False)
        console, buffer = _console()
        ui.render_error(console, "bad config", detail="missing key", hint="add it")
        out = buffer.getvalue()
        assert "error: bad config" in out
        assert "missing key" in out
        assert "hint: add it" in out

    def test_title_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ui, "should_decorate", lambda: True)
        console, buffer = _console()
        ui.render_error(console, "just a title")
        assert "just a title" in buffer.getvalue()

    def test_plain_title_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ui, "should_decorate", lambda: False)
        console, buffer = _console()
        ui.render_error(console, "boom")
        out = buffer.getvalue()
        assert "error: boom" in out
        assert "hint:" not in out


class TestRenderClean:
    def test_decorated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ui, "should_decorate", lambda: True)
        console, buffer = _console()
        ui.render_clean(console, "./src")
        out = buffer.getvalue()
        assert "No findings" in out
        assert "./src" in out

    def test_plain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ui, "should_decorate", lambda: False)
        console, buffer = _console()
        ui.render_clean(console, "./src")
        assert "ok: no findings in ./src" in buffer.getvalue()


class TestScanHeader:
    def test_static_only(self) -> None:
        console, buffer = _console()
        ui.render_scan_header(
            console, root="./x", scanner_count=4, engine="agent", sandbox=False, llm=False
        )
        out = buffer.getvalue()
        assert "scanning ./x" in out
        assert "4 scanner(s)" in out
        assert "static scanners" in out

    def test_agent_pipeline_with_sandbox(self) -> None:
        console, buffer = _console()
        ui.render_scan_header(
            console, root="./x", scanner_count=4, engine="langgraph", sandbox=True, llm=True
        )
        out = buffer.getvalue()
        assert "agent pipeline (langgraph)" in out
        assert "sandbox exploit verification" in out

    def test_agent_pipeline_without_sandbox(self) -> None:
        console, buffer = _console()
        ui.render_scan_header(
            console, root="./x", scanner_count=4, engine="agent", sandbox=False, llm=True
        )
        assert "agent pipeline (agent)" in buffer.getvalue()


class TestNextSteps:
    def test_no_findings_is_silent(self) -> None:
        console, buffer = _console()
        ui.render_next_steps(console, has_findings=False, machine_hint="anything")
        assert buffer.getvalue() == ""

    def test_with_findings_shows_hint(self) -> None:
        console, buffer = _console()
        ui.render_next_steps(console, has_findings=True, machine_hint="use --output")
        assert "use --output" in buffer.getvalue()


def test_symbols_are_defined() -> None:
    for key in ("ok", "fail", "warn", "info", "arrow", "bullet"):
        assert ui.SYMBOLS[key]
