"""A :class:`~cortexward.ports.ReporterPort` adapter rendering CortexWard's own JSON export.

Unlike `SarifReporter` (a deliberately narrowed *export* format, ADR-0003),
this reporter is a faithful, complete serialization of the internal
:class:`~cortexward.domain.Finding` model — every `Evidence` item, the
verification rung, provenance, timestamps, everything SARIF's single-message
`result` shape can't express. This is the format referenced as "future work"
in `SarifReporter`'s own module docstring: the place a caller goes when it
needs the full evidence trail an agent-verified finding carries (e.g. an
LLM_ASSESSMENT's reasoning text, or a REACHABILITY_PROOF's summary),
not just a finding's current state.

Delegates to pydantic's own `model_dump(mode="json")` rather than hand-
mapping fields: `Finding` (and everything it nests — `Evidence`,
`Provenance`, `SourceLocation`) is already a pydantic model, so this stays
automatically complete and in sync with the domain model as it evolves,
instead of silently drifting out of date the way a hand-maintained mapping
would.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from cortexward.core import version as core_version
from cortexward.domain import Finding
from cortexward.ports import RenderedArtifact


class JsonReporter:
    """Renders a set of `Finding`s into CortexWard's own complete JSON export."""

    format_id = "cortexward-json"

    def render(self, findings: Sequence[Finding]) -> RenderedArtifact:
        document = {
            "cortexward_version": core_version(),
            "findings": [finding.model_dump(mode="json") for finding in findings],
        }
        content = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            content=content, media_type="application/json", filename="cortexward.json"
        )


__all__ = ["JsonReporter"]
