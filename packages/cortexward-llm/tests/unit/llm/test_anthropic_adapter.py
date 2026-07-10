"""Unit tests for the Anthropic Messages API adapter.

All tests monkeypatch the adapter's own `_post` so the request/response
mapping is exercised deterministically against Anthropic's documented
Messages API schema — see the module docstring for why this isn't
live-verified (no credentials in this environment).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

import pytest

from cortexward.llm import AnthropicAdapter, AnthropicError
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort, TokenUsage, ToolSpec

pytestmark = pytest.mark.unit


class TestProtocolConformance:
    def test_satisfies_the_port(self) -> None:
        assert isinstance(AnthropicAdapter("claude-opus-4-8", api_key="k"), LLMPort)

    def test_model_id_is_the_configured_model(self) -> None:
        assert AnthropicAdapter("claude-opus-4-8", api_key="k").model_id == "claude-opus-4-8"


class TestRequestShape:
    def test_sends_model_messages_and_default_max_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            captured["payload"] = payload
            return {"content": [{"type": "text", "text": "hi"}]}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="sk-test")
        adapter.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hello"),))
        )
        assert captured["path"] == "/messages"
        assert captured["payload"]["model"] == "claude-opus-4-8"
        assert captured["payload"]["messages"] == [{"role": "user", "content": "hello"}]
        assert captured["payload"]["max_tokens"] == 4096
        assert "system" not in captured["payload"]

    def test_explicit_max_tokens_overrides_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"content": [{"type": "text", "text": "hi"}]}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="hi"),), max_tokens=256
            )
        )
        assert captured["payload"]["max_tokens"] == 256

    def test_system_messages_are_extracted_and_concatenated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"content": [{"type": "text", "text": "hi"}]}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(
                    ChatMessage(role=ChatRole.SYSTEM, content="Be terse."),
                    ChatMessage(role=ChatRole.SYSTEM, content="Never apologize."),
                    ChatMessage(role=ChatRole.USER, content="hi"),
                )
            )
        )
        assert captured["payload"]["system"] == "Be terse.\n\nNever apologize."
        assert captured["payload"]["messages"] == [{"role": "user", "content": "hi"}]

    def test_tool_role_messages_map_to_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"content": [{"type": "text", "text": "hi"}]}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.TOOL, content='{"result": 4}', name="add"),)
            )
        )
        assert captured["payload"]["messages"] == [{"role": "user", "content": '{"result": 4}'}]

    def test_includes_tools_using_input_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"content": [{"type": "text", "text": "ok"}]}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        tool = ToolSpec(name="add", description="Add", parameters_schema={"type": "object"})
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="2+2"),), tools=(tool,)
            )
        )
        assert captured["payload"]["tools"] == [
            {"name": "add", "description": "Add", "input_schema": {"type": "object"}}
        ]


class TestResponseMapping:
    def test_extracts_text_and_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "model": "claude-opus-4-8-20260101",
                "content": [{"type": "text", "text": "Hello!"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 12, "output_tokens": 3},
            }

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        result = AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text == "Hello!"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 3
        assert result.model == "claude-opus-4-8-20260101"
        assert result.stop_reason == "end_turn"

    def test_concatenates_multiple_text_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "content": [{"type": "text", "text": "Hello, "}, {"type": "text", "text": "world!"}]
            }

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        result = AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text == "Hello, world!"

    def test_parses_tool_use_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "add", "input": {"a": 2, "b": 3}}
                ]
            }

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        result = AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="2+3"),))
        )
        assert result.text is None
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.id == "toolu_1"
        assert call.name == "add"
        assert call.arguments == {"a": 2, "b": 3}

    @pytest.mark.parametrize(
        "malformed_content",
        [
            "not-a-list",
            [123],
            [{"type": "tool_use", "id": "x"}],
            [{"type": "tool_use", "id": "x", "name": 123, "input": {}}],
            [{"type": "tool_use", "id": "x", "name": "add", "input": "not-a-dict"}],
            [{"type": "unknown_block"}],
            [{"type": "text"}],
            [{"type": "text", "text": 123}],
        ],
    )
    def test_malformed_content_is_tolerated(
        self, monkeypatch: pytest.MonkeyPatch, malformed_content: object
    ) -> None:
        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            if not isinstance(malformed_content, list):
                return {"content": malformed_content}
            return {"content": malformed_content}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        if not isinstance(malformed_content, list):
            with pytest.raises(AnthropicError, match="content"):
                AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
                    CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
                )
        else:
            result = AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )
            assert result.tool_calls == ()

    def test_missing_content_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        with pytest.raises(AnthropicError, match="content"):
            AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_missing_usage_and_stop_reason_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: AnthropicAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "ok"}]}

        monkeypatch.setattr(AnthropicAdapter, "_post", _fake_post)
        result = AnthropicAdapter("claude-opus-4-8", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        assert result.stop_reason == "end_turn"


class TestPostErrorHandling:
    def test_connection_failure_raises_anthropic_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k", base_url="http://localhost:1")
        with pytest.raises(AnthropicError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_invalid_json_response_raises_anthropic_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeResponse:
            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"not json"

        monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse())
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        with pytest.raises(AnthropicError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )


class TestCostAndTokenEstimates:
    def test_cost_estimate_raises_not_implemented(self) -> None:
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        with pytest.raises(NotImplementedError):
            adapter.cost_estimate(TokenUsage(prompt_tokens=1, completion_tokens=1))

    def test_count_tokens_is_a_rough_heuristic(self) -> None:
        adapter = AnthropicAdapter("claude-opus-4-8", api_key="k")
        assert adapter.count_tokens("") == 0
        assert adapter.count_tokens("hi") == 1
