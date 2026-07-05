"""Reporter port: exporting findings as SARIF / VEX / SBOM / Markdown
(ADR-0003).

Each output format is an adapter behind this one contract; the internal
:class:`~cortexward.domain.Finding` model stays richer than any single
external format and is never coupled to one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from cortexward.domain import Finding
from cortexward.ports._base import PortModel


class RenderedArtifact(PortModel):
    """A rendered report, ready to write to disk or upload."""

    content: bytes
    media_type: str
    filename: str


@runtime_checkable
class ReporterPort(Protocol):
    """Renders a set of findings into one standards-aligned output format."""

    @property
    def format_id(self) -> str:
        """Stable identifier, e.g. ``"sarif"``, ``"cyclonedx-vex"``."""
        ...

    def render(self, findings: Sequence[Finding]) -> RenderedArtifact:
        """Render ``findings`` into this reporter's output format."""
        ...
