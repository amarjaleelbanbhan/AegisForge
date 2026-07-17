"""Conformance test for the Telemetry port."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from cortexward.ports import SpanHandle, TelemetryPort

pytestmark = pytest.mark.unit


class _RecordingSpan:
    def __init__(self, name: str, sink: list[str]) -> None:
        self._name = name
        self._sink = sink

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        self._sink.append(f"{self._name}.{key}={value}")

    def record_exception(self, error: BaseException) -> None:
        self._sink.append(f"{self._name}.exception={error}")


class _FakeTelemetry:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.metrics: list[tuple[str, float]] = []

    @contextmanager
    def span(self, name: str) -> Iterator[SpanHandle]:
        self.events.append(f"start:{name}")
        try:
            yield _RecordingSpan(name, self.events)
        finally:
            self.events.append(f"end:{name}")

    def record_metric(self, name: str, value: float, **attributes: str) -> None:
        self.metrics.append((name, value))


def test_fake_telemetry_satisfies_protocol() -> None:
    assert isinstance(_FakeTelemetry(), TelemetryPort)


def test_span_records_attributes_and_boundaries() -> None:
    telemetry = _FakeTelemetry()
    with telemetry.span("scan") as span:
        span.set_attribute("files", 12)
    assert telemetry.events == ["start:scan", "scan.files=12", "end:scan"]


def test_span_records_exception() -> None:
    telemetry = _FakeTelemetry()
    with pytest.raises(RuntimeError), telemetry.span("verify") as span:
        span.record_exception(RuntimeError("boom"))
        raise RuntimeError("boom")
    assert "verify.exception=boom" in telemetry.events


def test_record_metric() -> None:
    telemetry = _FakeTelemetry()
    telemetry.record_metric("cost_usd", 0.02, model="fake")
    assert telemetry.metrics == [("cost_usd", 0.02)]
