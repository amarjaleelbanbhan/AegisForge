"""AegisForge domain core.

Pure, framework-free domain model and services. This package has no I/O and no
dependency on any adapter (scanners, LLMs, sandboxes, storage). Everything the
rest of the system reasons about — findings, evidence, the Verification Ladder,
patches — is defined here so the core stays testable and stable while adapters
evolve around it.
"""

from __future__ import annotations

from aegisforge.domain.enums import (
    EvidenceKind,
    FindingState,
    Severity,
    VerificationRung,
    VexStatus,
)
from aegisforge.domain.models import (
    Evidence,
    Finding,
    Patch,
    Provenance,
    SourceLocation,
)
from aegisforge.domain.value_objects import Assessment
from aegisforge.domain.verification import (
    apply_assessment,
    assess,
    calibrate_confidence,
)

__all__ = [
    "Assessment",
    "Evidence",
    "EvidenceKind",
    "Finding",
    "FindingState",
    "Patch",
    "Provenance",
    "Severity",
    "SourceLocation",
    "VerificationRung",
    "VexStatus",
    "apply_assessment",
    "assess",
    "calibrate_confidence",
]
