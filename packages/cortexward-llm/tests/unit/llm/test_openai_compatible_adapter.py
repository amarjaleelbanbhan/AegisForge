"""Unit tests for the OpenAI-compatible adapter.

All tests monkeypatch the adapter's own `_post` so the request/response
mapping is exercised deterministically against OpenAI's documented Chat
Completions schema — see the module docstring for why this isn't
live-verified (no credentials in this environment).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

import pytest

from cortexward.llm import OpenAICompatibleAdapter, OpenAICompatibleError
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort, TokenUsage, ToolSpec

pytestmark = pytest.mark.unit


class TestProtocolConformance:
    def test_satisfies_the_port(self) -> None:
        assert isinstance(OpenAICompatibleAdapter("gpt-4o", api_key="k"), LLMPort)

    def test_model_id_is_the_configured_model(self) -> None:
        assert OpenAICompatibleAdapter("gpt-4o", api_key="k").model_id == "gpt-4o"


class TestRequestShape:
    def test_sends_model_messages_and_bearer_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            captured["payload"] = payload
            return {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="sk-test")
        adapter.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hello"),))
        )
        assert captured["path"] == "/chat/completions"
        assert captured["payload"]["model"] == "gpt-4o"
        assert captured["payload"]["messages"] == [{"role": "user", "content": "hello"}]

    def test_includes_tools_when_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        tool = ToolSpec(name="add", description="Add", parameters_schema={"type": "object"})
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="2+2"),), tools=(tool,)
            )
        )
        assert captured["payload"]["tools"] == [
            {
                "type": "function",
                "function": {"name": "add", "description": "Add", "parameters": {"type": "object"}},
            }
        ]

    def test_max_tokens_is_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="hi"),), max_tokens=256
            )
        )
        assert captured["payload"]["max_tokens"] == 256

    def test_message_name_is_included_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        adapter.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.TOOL, content="4", name="add"),))
        )
        assert captured["payload"]["messages"] == [{"role": "tool", "content": "4", "name": "add"}]

    def test_response_schema_maps_to_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"choices": [{"message": {"role": "assistant", "content": "{}"}}]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        schema: dict[str, object] = {"type": "object"}
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="hi"),), response_schema=schema
            )
        )
        assert captured["payload"]["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema},
        }


class TestResponseMapping:
    def test_extracts_text_and_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "model": "gpt-4o-2024-08-06",
                "choices": [
                    {"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            }

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        result = OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text == "Hello!"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 3
        assert result.model == "gpt-4o-2024-08-06"
        assert result.stop_reason == "stop"

    def test_parses_tool_calls_with_json_encoded_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        result = OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="2+3"),))
        )
        assert result.text is None
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.id == "call_abc"
        assert call.name == "add"
        assert call.arguments == {"a": 2, "b": 3}

    @pytest.mark.parametrize(
        "malformed_tool_calls",
        [
            "not-a-list",
            [123],
            [{"id": "x"}],
            [{"id": "x", "function": {"name": 123, "arguments": "{}"}}],
            [{"id": "x", "function": {"name": "add", "arguments": "not-json"}}],
            [{"id": "x", "function": {"name": "add", "arguments": "[1, 2]"}}],
        ],
    )
    def test_malformed_tool_calls_are_tolerated(
        self, monkeypatch: pytest.MonkeyPatch, malformed_tool_calls: object
    ) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": malformed_tool_calls,
                        }
                    }
                ]
            }

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        result = OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.tool_calls == ()

    def test_missing_choices_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        with pytest.raises(OpenAICompatibleError, match="choices"):
            OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_empty_choices_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"choices": []}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        with pytest.raises(OpenAICompatibleError, match="choices"):
            OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_missing_message_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"choices": [{}]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        with pytest.raises(OpenAICompatibleError, match="message"):
            OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_malformed_choice_entry_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OpenAICompatibleAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"choices": ["not-a-dict"]}

        monkeypatch.setattr(OpenAICompatibleAdapter, "_post", _fake_post)
        with pytest.raises(OpenAICompatibleError, match="malformed choice"):
            OpenAICompatibleAdapter("gpt-4o", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )


class TestPostErrorHandling:
    def test_connection_failure_raises_openai_compatible_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k", base_url="http://localhost:1")
        with pytest.raises(OpenAICompatibleError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_invalid_json_response_raises_openai_compatible_error(
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
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        with pytest.raises(OpenAICompatibleError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )


class TestCostAndTokenEstimates:
    def test_cost_estimate_raises_not_implemented(self) -> None:
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        with pytest.raises(NotImplementedError):
            adapter.cost_estimate(TokenUsage(prompt_tokens=1, completion_tokens=1))

    def test_count_tokens_is_a_rough_heuristic(self) -> None:
        adapter = OpenAICompatibleAdapter("gpt-4o", api_key="k")
        assert adapter.count_tokens("") == 0
        assert adapter.count_tokens("hi") == 1
