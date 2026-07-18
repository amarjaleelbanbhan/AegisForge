"""Unit tests for `cortexward.agents.threat_model.build_threat_model`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from cortexward.agents.threat_model import build_threat_model
from cortexward.domain import Finding, Provenance, Severity, SourceLocation, StrideCategory
from cortexward.ports import NodeId, TaintPath

pytestmark = pytest.mark.unit


class _FakeCodeGraph:
    """A `CodeGraph` whose `reachable()`/`taint()`/`nodes_at()`/`entrypoints()` are scripted."""

    language = "python"

    def __init__(
        self,
        *,
        entrypoints: Sequence[NodeId] = (),
        nodes_by_location: Mapping[tuple[str, int], Sequence[NodeId]] | None = None,
        reachable_sinks: Sequence[NodeId] = (),
        taint_paths: Sequence[TaintPath] = (),
    ) -> None:
        self._entrypoints = tuple(entrypoints)
        self._nodes_by_location = dict(nodes_by_location or {})
        self._reachable_sinks = set(reachable_sinks)
        self._taint_paths = tuple(taint_paths)

    def entrypoints(self) -> Sequence[NodeId]:
        return self._entrypoints

    def reachable(self, sources: Sequence[NodeId], sink: NodeId) -> bool:
        return sink in self._reachable_sinks

    def taint(
        self, sources: Sequence[NodeId], sinks: Sequence[NodeId], sanitizers: Sequence[NodeId] = ()
    ) -> Sequence[TaintPath]:
        return tuple(path for path in self._taint_paths if path.sink in sinks)

    def callers(self, function: NodeId) -> Sequence[NodeId]:
        return ()

    def slice(self, node: NodeId) -> Sequence[NodeId]:
        return ()

    def location_of(self, node: NodeId) -> SourceLocation:
        raise KeyError(node)

    def nodes_at(self, path: str, line: int) -> Sequence[NodeId]:
        return self._nodes_by_location.get((path, line), ())


def _finding(
    *,
    rule_id: str = "B602",
    cwe: int | None = 78,
    path: str = "app.py",
    line: int = 3,
    severity: Severity = Severity.HIGH,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        title="t",
        message="m",
        cwe=cwe,
        severity=severity,
        locations=(SourceLocation(path=path, start_line=line),),
        provenance=Provenance(producer="test"),
    )


class TestBuildThreatModel:
    def test_no_findings_yields_an_empty_threat_model(self) -> None:
        model = build_threat_model([])
        assert model.threats == ()

    def test_a_finding_with_no_cwe_contributes_no_threat(self) -> None:
        model = build_threat_model([_finding(cwe=None)])
        assert model.threats == ()

    def test_a_finding_with_an_unmapped_cwe_contributes_no_threat(self) -> None:
        model = build_threat_model([_finding(cwe=999_999)])
        assert model.threats == ()

    def test_a_mapped_finding_becomes_a_threat(self) -> None:
        finding = _finding(cwe=78)  # OS Command Injection
        model = build_threat_model([finding])
        assert len(model.threats) == 1
        threat = model.threats[0]
        assert threat.finding_id == finding.id
        assert threat.rule_id == "B602"
        assert threat.cwe == 78
        assert StrideCategory.TAMPERING in threat.categories
        assert threat.severity == Severity.HIGH
        assert threat.location == finding.locations[0]

    def test_no_code_graphs_leaves_every_threat_unreachable(self) -> None:
        model = build_threat_model([_finding()])
        assert model.threats[0].reachable_from_entrypoint is False
        assert model.threats[0].crosses_trust_boundary is False

    def test_a_finding_with_no_location_is_not_reachable(self) -> None:
        finding = Finding(
            rule_id="B602", title="t", message="m", cwe=78, provenance=Provenance(producer="test")
        )
        model = build_threat_model([finding])
        assert model.threats[0].location is None
        assert model.threats[0].reachable_from_entrypoint is False
        assert model.threats[0].crosses_trust_boundary is False

    def test_a_genuinely_reachable_finding_is_marked_exposed(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=("ep",), nodes_by_location={("app.py", 3): ("n1",)}, reachable_sinks=("n1",)
        )
        model = build_threat_model([_finding()], {"python": graph})
        assert model.threats[0].reachable_from_entrypoint is True
        assert model.threats[0] in model.exposed

    def test_a_genuine_taint_path_marks_the_trust_boundary_crossed(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=("ep",),
            nodes_by_location={("app.py", 3): ("n1",)},
            taint_paths=(TaintPath(source="ep", sink="n1", path=("ep", "n1")),),
        )
        model = build_threat_model([_finding()], {"python": graph})
        assert model.threats[0].crosses_trust_boundary is True
        assert model.threats[0] in model.boundary_crossings

    def test_a_sanitized_taint_path_leaves_the_boundary_uncrossed(self) -> None:
        graph = _FakeCodeGraph(
            entrypoints=("ep",),
            nodes_by_location={("app.py", 3): ("n1",)},
            taint_paths=(TaintPath(source="ep", sink="n1", path=("ep", "n1"), sanitized=True),),
        )
        model = build_threat_model([_finding()], {"python": graph})
        assert model.threats[0].crosses_trust_boundary is False
        assert model.threats[0] not in model.boundary_crossings

    def test_multiple_findings_each_become_their_own_threat(self) -> None:
        findings = [
            _finding(rule_id="B602", cwe=78, line=3),
            _finding(rule_id="B105", cwe=798, line=5),
        ]
        model = build_threat_model(findings)
        assert {threat.rule_id for threat in model.threats} == {"B602", "B105"}

    def test_mixed_mapped_and_unmapped_findings_only_the_mapped_ones_appear(self) -> None:
        findings = [_finding(cwe=78), _finding(cwe=None, line=5), _finding(cwe=999_999, line=7)]
        model = build_threat_model(findings)
        assert len(model.threats) == 1
        assert model.threats[0].cwe == 78
