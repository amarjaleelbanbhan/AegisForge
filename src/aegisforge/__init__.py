"""AegisForge — an autonomous AI software security engineer.

AegisForge understands, verifies, fixes, and secures software. This top-level
package exposes the version and re-exports the stable domain vocabulary; heavier
subsystems live in submodules and are imported explicitly to keep import time
and the dependency surface small.
"""

from __future__ import annotations

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
