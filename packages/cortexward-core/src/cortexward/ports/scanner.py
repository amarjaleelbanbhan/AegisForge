"""Scanner port: adapters for SAST/secret/dependency scanners (MPS §17.1).

A scanner adapter yields :class:`RawFinding` records — its native output,
before cross-tool deduplication and fingerprinting (Phase 3) normalize them
into :class:`cortexward.domain.Finding`. Keeping the raw shape separate from
the domain aggregate lets each scanner report exactly what it found without
forcing premature decisions about identity or evidence weight.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field

from cortexward.domain import SourceLocation
from cortexward.ports._base import PortModel


class RawFinding(PortModel):
    """One unnormalized detection from a single scanner adapter."""

    rule_id: str
    message: str
    location: SourceLocation
    severity_hint: str | None = None
    cwe: int | None = None
    raw: dict[str, str] = Field(default_factory=dict)
    """The scanner's own fields, preserved for audit and debugging."""


@runtime_checkable
class ScannerPort(Protocol):
    """A single static analysis / secret / dependency scanner adapter."""

    @property
    def name(self) -> str:
        """Stable identifier for this scanner, e.g. ``"semgrep"``."""
        ...

    def scan(self, root: Path, *, languages: Sequence[str] = ()) -> Iterable[RawFinding]:
        """Run this scanner over ``root`` and yield its raw findings.

        ``languages`` optionally restricts the scan to the given language
        identifiers; an empty sequence means "whatever this scanner supports".
        """
        ...
