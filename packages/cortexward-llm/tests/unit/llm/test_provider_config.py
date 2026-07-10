"""Unit tests for the provider-agnostic `LLMProviderConfig`/`build_llm` factory.

`build_llm` is the one place in the codebase allowed to branch on provider
identity — these tests confirm every `Provider` value routes to the
expected adapter type and base URL, and that misconfiguration raises
`LLMConfigError` with a clear reason rather than a bare exception deep
inside an adapter constructor.
"""

from __future__ import annotations

import pytest

from cortexward.llm import (
    AnthropicAdapter,
    GeminiAdapter,
    LLMConfigError,
    LLMProviderConfig,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    Provider,
    build_llm,
)

pytestmark = pytest.mark.unit


class TestOllama:
    def test_builds_an_ollama_adapter_with_default_base_url(self) -> None:
        llm = build_llm(LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b"))
        assert isinstance(llm, OllamaAdapter)
        assert llm.model_id == "qwen2.5-coder:7b"

    def test_honors_an_explicit_base_url(self) -> None:
        llm = build_llm(
            LLMProviderConfig(
                provider=Provider.OLLAMA, model="qwen2.5-coder:7b", base_url="http://gpu-box:11434"
            )
        )
        assert isinstance(llm, OllamaAdapter)

    def test_needs_no_api_key(self) -> None:
        llm = build_llm(LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b"))
        assert isinstance(llm, OllamaAdapter)


class TestAnthropic:
    def test_builds_an_anthropic_adapter(self) -> None:
        llm = build_llm(
            LLMProviderConfig(provider=Provider.ANTHROPIC, model="claude-opus-4-8", api_key="k")
        )
        assert isinstance(llm, AnthropicAdapter)
        assert llm.model_id == "claude-opus-4-8"

    def test_honors_an_explicit_base_url(self) -> None:
        llm = build_llm(
            LLMProviderConfig(
                provider=Provider.ANTHROPIC,
                model="claude-opus-4-8",
                api_key="k",
                base_url="https://gateway.internal/anthropic",
            )
        )
        assert isinstance(llm, AnthropicAdapter)

    def test_missing_api_key_raises(self) -> None:
        with pytest.raises(LLMConfigError, match="api_key"):
            build_llm(LLMProviderConfig(provider=Provider.ANTHROPIC, model="claude-opus-4-8"))

    def test_reads_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_ANTHROPIC_KEY", "sk-from-env")
        llm = build_llm(
            LLMProviderConfig(
                provider=Provider.ANTHROPIC, model="claude-opus-4-8", api_key_env="MY_ANTHROPIC_KEY"
            )
        )
        assert isinstance(llm, AnthropicAdapter)


class TestGemini:
    def test_builds_a_gemini_adapter(self) -> None:
        llm = build_llm(
            LLMProviderConfig(provider=Provider.GEMINI, model="gemini-2.5-pro", api_key="k")
        )
        assert isinstance(llm, GeminiAdapter)
        assert llm.model_id == "gemini-2.5-pro"

    def test_honors_an_explicit_base_url(self) -> None:
        llm = build_llm(
            LLMProviderConfig(
                provider=Provider.GEMINI,
                model="gemini-2.5-pro",
                api_key="k",
                base_url="https://gateway.internal/gemini",
            )
        )
        assert isinstance(llm, GeminiAdapter)

    def test_missing_api_key_raises(self) -> None:
        with pytest.raises(LLMConfigError, match="api_key"):
            build_llm(LLMProviderConfig(provider=Provider.GEMINI, model="gemini-2.5-pro"))


class TestOpenAICompatibleFamily:
    @pytest.mark.parametrize(
        ("provider", "expected_base_url"),
        [
            (Provider.OPENAI, "https://api.openai.com/v1"),
            (Provider.GROQ, "https://api.groq.com/openai/v1"),
            (Provider.OPENROUTER, "https://openrouter.ai/api/v1"),
            (Provider.LM_STUDIO, "http://localhost:1234/v1"),
        ],
    )
    def test_uses_the_known_default_base_url(
        self, provider: Provider, expected_base_url: str
    ) -> None:
        llm = build_llm(LLMProviderConfig(provider=provider, model="some-model", api_key="k"))
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_explicit_base_url_overrides_the_default(self) -> None:
        llm = build_llm(
            LLMProviderConfig(
                provider=Provider.OPENAI,
                model="gpt-5",
                api_key="k",
                base_url="https://my-gateway/v1",
            )
        )
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_vllm_needs_an_explicit_base_url(self) -> None:
        with pytest.raises(LLMConfigError, match="base_url"):
            build_llm(LLMProviderConfig(provider=Provider.VLLM, model="local-model"))

    def test_vllm_with_explicit_base_url_builds(self) -> None:
        llm = build_llm(
            LLMProviderConfig(
                provider=Provider.VLLM, model="local-model", base_url="http://localhost:8000/v1"
            )
        )
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_missing_api_key_defaults_to_empty_string_not_an_error(self) -> None:
        llm = build_llm(LLMProviderConfig(provider=Provider.LM_STUDIO, model="local-model"))
        assert isinstance(llm, OpenAICompatibleAdapter)


class TestUnknownProvider:
    def test_a_non_member_provider_value_raises(self) -> None:
        bogus_config = LLMProviderConfig(provider="not-a-real-provider", model="x")  # type: ignore[arg-type]
        with pytest.raises(LLMConfigError, match="unknown provider"):
            build_llm(bogus_config)


class TestResolvedApiKey:
    def test_literal_key_takes_precedence_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOME_KEY", "from-env")
        config = LLMProviderConfig(
            provider=Provider.ANTHROPIC, model="x", api_key="from-literal", api_key_env="SOME_KEY"
        )
        assert config.resolved_api_key() == "from-literal"

    def test_env_key_used_when_literal_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOME_KEY", "from-env")
        config = LLMProviderConfig(provider=Provider.ANTHROPIC, model="x", api_key_env="SOME_KEY")
        assert config.resolved_api_key() == "from-env"

    def test_none_when_neither_is_set(self) -> None:
        config = LLMProviderConfig(provider=Provider.ANTHROPIC, model="x")
        assert config.resolved_api_key() is None

    def test_none_when_env_var_is_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEFINITELY_NOT_SET_KEY", raising=False)
        config = LLMProviderConfig(
            provider=Provider.ANTHROPIC, model="x", api_key_env="DEFINITELY_NOT_SET_KEY"
        )
        assert config.resolved_api_key() is None
