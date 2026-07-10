"""Unit tests for `load_llm_config`.

Writes real YAML files to `tmp_path` rather than mocking the filesystem or
`yaml.safe_load`, per this codebase's established preference for exercising
real I/O wherever the target is genuinely reachable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.llm import LLMConfigError, Provider, load_llm_config

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, text: str) -> Path:
    config_path = tmp_path / "llm.yaml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


class TestSuccessfulLoads:
    def test_ollama(self, tmp_path: Path) -> None:
        config = load_llm_config(_write(tmp_path, "provider: ollama\nmodel: qwen2.5-coder:7b\n"))
        assert config.provider == Provider.OLLAMA
        assert config.model == "qwen2.5-coder:7b"
        assert config.api_key is None
        assert config.api_key_env is None
        assert config.base_url is None

    def test_openai_with_api_key_env(self, tmp_path: Path) -> None:
        config = load_llm_config(
            _write(tmp_path, "provider: openai\nmodel: gpt-5\napi_key_env: OPENAI_API_KEY\n")
        )
        assert config.provider == Provider.OPENAI
        assert config.model == "gpt-5"
        assert config.api_key_env == "OPENAI_API_KEY"

    def test_anthropic_with_literal_api_key(self, tmp_path: Path) -> None:
        config = load_llm_config(
            _write(tmp_path, "provider: anthropic\nmodel: claude-opus-4-8\napi_key: sk-test\n")
        )
        assert config.provider == Provider.ANTHROPIC
        assert config.api_key == "sk-test"

    def test_gemini(self, tmp_path: Path) -> None:
        config = load_llm_config(
            _write(
                tmp_path, "provider: gemini\nmodel: gemini-2.5-pro\napi_key_env: GEMINI_API_KEY\n"
            )
        )
        assert config.provider == Provider.GEMINI
        assert config.model == "gemini-2.5-pro"

    def test_base_url_is_read_when_present(self, tmp_path: Path) -> None:
        config = load_llm_config(
            _write(
                tmp_path,
                "provider: vllm\nmodel: local-model\nbase_url: http://localhost:8000/v1\n",
            )
        )
        assert config.base_url == "http://localhost:8000/v1"


class TestMalformedConfig:
    def test_invalid_yaml_syntax_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="invalid YAML"):
            load_llm_config(_write(tmp_path, "provider: [unterminated\n"))

    def test_non_dict_top_level_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="mapping"):
            load_llm_config(_write(tmp_path, "- just\n- a\n- list\n"))

    def test_missing_provider_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="provider"):
            load_llm_config(_write(tmp_path, "model: gpt-5\n"))

    def test_non_string_provider_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="provider"):
            load_llm_config(_write(tmp_path, "provider: 123\nmodel: gpt-5\n"))

    def test_unknown_provider_raises_and_lists_valid_values(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="unknown provider") as exc_info:
            load_llm_config(_write(tmp_path, "provider: watsonx\nmodel: x\n"))
        assert "ollama" in str(exc_info.value)

    def test_missing_model_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="model"):
            load_llm_config(_write(tmp_path, "provider: ollama\n"))

    def test_non_string_model_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LLMConfigError, match="model"):
            load_llm_config(_write(tmp_path, "provider: ollama\nmodel: 123\n"))

    @pytest.mark.parametrize("field", ["api_key", "api_key_env", "base_url"])
    def test_non_string_optional_field_raises(self, tmp_path: Path, field: str) -> None:
        with pytest.raises(LLMConfigError, match=field):
            load_llm_config(_write(tmp_path, f"provider: ollama\nmodel: x\n{field}: 123\n"))
