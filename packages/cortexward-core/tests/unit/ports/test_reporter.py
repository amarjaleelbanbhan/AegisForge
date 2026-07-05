"""Conformance test for the Reporter port."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import pytest

from cortexward.domain import Finding
from cortexward.ports import RenderedArtifact, ReporterPort

pytestmark = pytest.mark.unit


class _FakeJsonReporter:
    format_id = "fake-json"

    def render(self, findings: Sequence[Finding]) -> RenderedArtifact:
        payload = json.dumps([f.id for f in findings]).encode("utf-8")
        return RenderedArtifact(content=payload, media_type="application/json", filename="out.json")


def test_fake_reporter_satisfies_protocol() -> None:
    assert isinstance(_FakeJsonReporter(), ReporterPort)


def test_render_includes_every_finding(make_finding: Callable[..., Finding]) -> None:
    findings = (make_finding(), make_finding())
    artifact = _FakeJsonReporter().render(findings)
    decoded = json.loads(artifact.content)
    assert decoded == [f.id for f in findings]
    assert artifact.media_type == "application/json"
