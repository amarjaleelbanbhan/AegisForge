"""Loads an `LLMProviderConfig` from a YAML file (MPS §14).

The whole point of `LLMProviderConfig`/`build_llm` is that switching
providers is a configuration change, not a code change — this is the
loader that turns a small YAML file like:

    provider: ollama
    model: qwen2.5-coder:7b

or

    provider: openai
    model: gpt-5
    api_key_env: OPENAI_API_KEY

into that config. YAML content is treated as untrusted, structured input
(ADR-0004's spirit applied to config, not just analyzed source): malformed
or incomplete files raise `LLMConfigError` with a clear reason rather than
a bare `KeyError`/`TypeError` from deep inside this function.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from cortexward.llm.provider_config import LLMConfigError, LLMProviderConfig, Provider


def load_llm_config(path: Path) -> LLMProviderConfig:
    """Loads one `LLMProviderConfig` from the YAML file at `path`."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LLMConfigError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise LLMConfigError(f"{path}: expected a YAML mapping at the top level")

    raw_provider = raw.get("provider")
    if not isinstance(raw_provider, str):
        raise LLMConfigError(f"{path}: missing or non-string required field 'provider'")
    try:
        provider = Provider(raw_provider)
    except ValueError as exc:
        valid = ", ".join(p.value for p in Provider)
        raise LLMConfigError(
            f"{path}: unknown provider {raw_provider!r}; expected one of: {valid}"
        ) from exc

    model = raw.get("model")
    if not isinstance(model, str):
        raise LLMConfigError(f"{path}: missing or non-string required field 'model'")

    return LLMProviderConfig(
        provider=provider,
        model=model,
        api_key=_optional_str(raw, "api_key", path),
        api_key_env=_optional_str(raw, "api_key_env", path),
        base_url=_optional_str(raw, "base_url", path),
    )


def _optional_str(raw: dict[str, object], key: str, path: Path) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LLMConfigError(f"{path}: field {key!r} must be a string if present")
    return value


__all__ = ["load_llm_config"]
