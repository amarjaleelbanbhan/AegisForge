"""Telemetry port: tracing every agent step, tool call, and model call.

OpenTelemetry is the reference adapter (MPS NFR-6), but nothing above this
port imports the ``opentelemetry`` package directly. Per-run ablation studies
depend on this instrumentation existing from the moment agents exist
(ADR-0007), so the contract is specified now even though the OTel adapter
lands with the agent framework (Phase 4).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class SpanHandle(Protocol):
    """A single open tracing span."""

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Attach a key/value attribute to the current span."""
        ...

    def record_exception(self, error: BaseException) -> None:
        """Record that ``error`` occurred within this span."""
        ...


@runtime_checkable
class TelemetryPort(Protocol):
    """Tracing and cost/metric accounting for one run."""

    def span(self, name: str) -> AbstractContextManager[SpanHandle]:
        """Open a new span named ``name`` for the duration of a ``with`` block."""
        ...

    def record_metric(self, name: str, value: float, **attributes: str) -> None:
        """Record a point metric, e.g. token cost or cache hit rate."""
        ...
