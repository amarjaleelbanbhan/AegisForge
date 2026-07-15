"""Builds `CodeGraph`s for a run, so `VerifierAgent` can attach independent
reachability evidence (MPS §13's "reachability, taint, sandbox PoC" line for
the Verifier) rather than relying on LLM judgement alone.

Auto-discovers `LanguageProvider`s via the plugin registry, the same
pattern `cortexward.orchestrator.sequential.default_scanners()` uses for
scanners — zero hardcoded language list. Building a graph needs a real
parse of the target root, which can legitimately find nothing (no matching
language, an empty directory, a provider that doesn't detect anything under
`root`) or fail outright (a provider bug, an unreadable file) — both are
non-fatal: a run with no usable code graph still verifies findings via the
LLM alone, exactly as if this module didn't exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from cortexward.plugins.groups import PluginGroup
from cortexward.plugins.registry import registry_for
from cortexward.ports import CodeGraph, LanguageProvider


def build_code_graphs(root: Path, *, languages: Sequence[str] = ()) -> dict[str, CodeGraph]:
    """Parses `root` with every applicable registered `LanguageProvider`.

    A provider is applicable if `languages` names its `.language` value
    explicitly, or — when `languages` is empty — if the provider's own
    `.detect(root)` recognizes something under `root`. A provider that
    raises while parsing is skipped: one broken or unsupported language
    must not abort reachability analysis for every other language in the
    same run.
    """
    registry = registry_for(PluginGroup.LANGUAGES)
    graphs: dict[str, CodeGraph] = {}
    for name in registry.available():
        provider = cast("LanguageProvider", registry.create(name))
        if languages:
            if provider.language not in languages:
                continue
        elif not provider.detect(root):
            continue
        try:
            graph = provider.parse(root)
        # One broken/unsupported language must not abort reachability
        # analysis for every other language in the same run.
        except Exception:  # noqa: S112 # nosec B112
            continue
        graphs[provider.language] = graph
    return graphs


__all__ = ["build_code_graphs"]
