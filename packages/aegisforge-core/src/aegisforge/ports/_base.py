"""Shared base for port-level data-transfer objects.

Ports may define their own small, immutable DTOs for data that crosses a
boundary but is not part of the domain aggregate (e.g. a scanner's raw,
pre-normalization output). These live under ``aegisforge.ports``, never
``aegisforge.domain``, so the domain core stays free of port concerns.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PortModel(BaseModel):
    """Frozen, strict base for port request/response value objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")
