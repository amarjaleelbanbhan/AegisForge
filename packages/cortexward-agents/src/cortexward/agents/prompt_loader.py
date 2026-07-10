"""Versioned prompt templates (MPS §15): `prompts/<name>/<version>.md`.

Templates ship as package data under `cortexward/agents/prompts/`, not a
repo-root-relative path — a path computed relative to a source checkout
would silently break once this package is installed as a wheel (there is
no `prompts/` directory a few parents above `site-packages`). Loading
relative to `__file__` within the package itself works identically
whether the package is installed editable or as a built wheel.

Each template file uses `{variable}`-style placeholders (`str.format`
syntax); the template's declared input schema is derived directly from the
placeholders it contains, so there's no separate schema file to keep in
sync by hand. `PromptTemplate.content_hash` is a stable hash of the
template body, recorded as the `prompt_version` on a `RunManifest` (MPS
§15) so the exact wording used in a run is reproducible, not just its
`name/version` label (which a human could edit without bumping).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class PromptNotFoundError(LookupError):
    """Raised when no prompt file exists for the requested name/version."""


class MissingPromptInputError(ValueError):
    """Raised when `render()` is called without every input the template declares."""


@dataclass(frozen=True)
class PromptTemplate:
    """One loaded, versioned prompt template."""

    name: str
    version: str
    body: str
    content_hash: str
    inputs: tuple[str, ...]

    def render(self, **values: object) -> str:
        missing = set(self.inputs) - values.keys()
        if missing:
            raise MissingPromptInputError(
                f"prompt {self.name}/{self.version} is missing input(s): {sorted(missing)}"
            )
        return self.body.format(**values)


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str, version: str, *, prompts_dir: Path | None = None) -> PromptTemplate:
    """Loads `<prompts_dir>/<name>/<version>.md` into a `PromptTemplate`.

    `prompts_dir` defaults to this package's own bundled `prompts/`
    directory; a caller can point at a different directory (e.g. a
    repo-specific prompt override set) without any other code change.
    """
    directory = prompts_dir if prompts_dir is not None else _prompts_dir()
    path = directory / name / f"{version}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"no prompt file at {path}")
    body = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    inputs = tuple(sorted(set(_PLACEHOLDER.findall(body))))
    return PromptTemplate(
        name=name, version=version, body=body, content_hash=content_hash, inputs=inputs
    )


__all__ = ["MissingPromptInputError", "PromptNotFoundError", "PromptTemplate", "load_prompt"]
