"""Unit tests for the CPG node/edge schema."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from aegisforge.cpg import Edge, EdgeKind, Node, NodeKind
from aegisforge.domain import SourceLocation

pytestmark = pytest.mark.unit

MakeLocation = Callable[..., SourceLocation]


class TestNode:
    def test_defaults(self, make_location: MakeLocation) -> None:
        node = Node(
            id="fn:handler", kind=NodeKind.FUNCTION, language="python", location=make_location()
        )
        assert node.properties == {}

    def test_is_frozen(self, make_location: MakeLocation) -> None:
        node = Node(
            id="fn:handler", kind=NodeKind.FUNCTION, language="python", location=make_location()
        )
        with pytest.raises(ValidationError):
            node.id = "fn:other"  # type: ignore[misc]

    def test_rejects_unknown_fields(self, make_location: MakeLocation) -> None:
        with pytest.raises(ValidationError):
            Node(
                id="fn:handler",
                kind=NodeKind.FUNCTION,
                language="python",
                location=make_location(),
                unexpected=True,  # type: ignore[call-arg]
            )


class TestEdge:
    def test_construction(self) -> None:
        edge = Edge(kind=EdgeKind.CALLS, source="fn:handler", target="fn:build_query")
        assert edge.kind is EdgeKind.CALLS

    def test_is_frozen(self) -> None:
        edge = Edge(kind=EdgeKind.CALLS, source="a", target="b")
        with pytest.raises(ValidationError):
            edge.source = "c"  # type: ignore[misc]
