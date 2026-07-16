"""CortexWard domain core.

Pure, framework-free domain model and services. This package has no I/O and no
dependency on any adapter (scanners, LLMs, sandboxes, storage). Everything the
rest of the system reasons about — findings, evidence, the Verification Ladder,
patches — is defined here so the core stays testable and stable while adapters
evolve around it.
"""

from __future__ import annotations

from cortexward.domain.enums import (
    EvidenceKind,
    FindingState,
    Severity,
    VerificationRung,
    VexStatus,
)
from cortexward.domain.fingerprint import fingerprint_for
from cortexward.domain.models import (
    Evidence,
    Finding,
    Patch,
    Provenance,
    SourceLocation,
)
from cortexward.domain.value_objects import Assessment
from cortexward.domain.verification import (
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
    "fingerprint_for",
]
