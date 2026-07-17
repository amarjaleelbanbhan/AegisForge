"""CortexWard scanner adapters (MPS §17.1)."""

from __future__ import annotations

from cortexward.scanners._normalize import correlate, normalize
from cortexward.scanners.bandit_scanner import BanditScanner
from cortexward.scanners.osv_scanner import OsvScanner
from cortexward.scanners.secrets_scanner import SecretsScanner
from cortexward.scanners.semgrep_scanner import SemgrepScanner

__all__ = [
    "BanditScanner",
    "OsvScanner",
    "SecretsScanner",
    "SemgrepScanner",
    "correlate",
    "normalize",
]
