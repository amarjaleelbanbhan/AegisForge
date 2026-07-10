"""Config-driven `LLMPort` selection (MPS §14): one config, any provider.

CortexWard never depends on a specific LLM provider — every capability
talks to `LLMPort` only. `build_llm` is the *one* place in the codebase
that branches on provider identity; switching providers is a configuration
change, never an application-code change:

    provider: ollama
    model: qwen2.5-coder:7b

or

    provider: openai
    model: gpt-5
    api_key_env: OPENAI_API_KEY

Every provider below `OllamaAdapter` is not live-verified in this
environment (no credentials) — see each adapter module's own docstring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from cortexward.llm.anthropic_adapter import AnthropicAdapter
from cortexward.llm.gemini_adapter import GeminiAdapter
from cortexward.llm.ollama_adapter import OllamaAdapter
from cortexward.llm.openai_compatible_adapter import OpenAICompatibleAdapter
from cortexward.ports import LLMPort


class Provider(StrEnum):
    """Every backend `build_llm` knows how to construct."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    LM_STUDIO = "lm_studio"
    VLLM = "vllm"


_OPENAI_COMPATIBLE_BASE_URLS: dict[Provider, str] = {
    Provider.OPENAI: "https://api.openai.com/v1",
    Provider.GROQ: "https://api.groq.com/openai/v1",
    Provider.OPENROUTER: "https://openrouter.ai/api/v1",
    Provider.LM_STUDIO: "http://localhost:1234/v1",
}
_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"


class LLMConfigError(ValueError):
    """Raised when an `LLMProviderConfig` is missing something its provider needs."""


@dataclass(frozen=True)
class LLMProviderConfig:
    """A declarative, provider-agnostic description of one `LLMPort` to build.

    `api_key`/`api_key_env` are both optional, and at most one should be
    set for a provider that needs a key at all: `api_key` is a literal
    value (convenient for tests, risky to commit to a config file),
    `api_key_env` names an environment variable to read the key from
    instead — the recommended path for anything real. Never commit a real
    key to a YAML config file that ends up in version control.
    """

    provider: Provider
    model: str
    api_key: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None

    def resolved_api_key(self) -> str | None:
        """`api_key` if set, else the value of `api_key_env` in the environment, else `None`."""
        if self.api_key is not None:
            return self.api_key
        if self.api_key_env is not None:
            return os.environ.get(self.api_key_env)
        return None


def build_llm(config: LLMProviderConfig) -> LLMPort:
    """Builds the `LLMPort` adapter `config` describes.

    This is the *only* place in CortexWard that branches on provider
    identity — every other component depends on `LLMPort` alone.
    """
    if config.provider == Provider.OLLAMA:
        return OllamaAdapter(config.model, base_url=config.base_url or _OLLAMA_DEFAULT_BASE_URL)

    if config.provider == Provider.ANTHROPIC:
        api_key = _require_api_key(config)
        return (
            AnthropicAdapter(config.model, api_key=api_key, base_url=config.base_url)
            if config.base_url
            else AnthropicAdapter(config.model, api_key=api_key)
        )

    if config.provider == Provider.GEMINI:
        api_key = _require_api_key(config)
        return (
            GeminiAdapter(config.model, api_key=api_key, base_url=config.base_url)
            if config.base_url
            else GeminiAdapter(config.model, api_key=api_key)
        )

    if config.provider == Provider.VLLM or config.provider in _OPENAI_COMPATIBLE_BASE_URLS:
        base_url = config.base_url or _OPENAI_COMPATIBLE_BASE_URLS.get(config.provider)
        if base_url is None:
            raise LLMConfigError(f"provider {config.provider!r} needs an explicit base_url")
        api_key = config.resolved_api_key() or ""  # vLLM/LM Studio commonly need no real key
        return OpenAICompatibleAdapter(config.model, api_key=api_key, base_url=base_url)

    raise LLMConfigError(f"unknown provider {config.provider!r}")


def _require_api_key(config: LLMProviderConfig) -> str:
    api_key = config.resolved_api_key()
    if not api_key:
        raise LLMConfigError(
            f"provider {config.provider.value!r} needs an api_key or api_key_env in its config"
        )
    return api_key


__all__ = ["LLMConfigError", "LLMProviderConfig", "Provider", "build_llm"]
