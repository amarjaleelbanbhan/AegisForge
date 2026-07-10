"""Unit tests for the Gemini `generateContent` adapter.

All tests monkeypatch the adapter's own `_post` so the request/response
mapping is exercised deterministically against Google's documented
`generateContent` REST schema — see the module docstring for why this
isn't live-verified (no credentials in this environment).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

import pytest

from cortexward.llm import GeminiAdapter, GeminiError
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, LLMPort, TokenUsage, ToolSpec

pytestmark = pytest.mark.unit


class TestProtocolConformance:
    def test_satisfies_the_port(self) -> None:
        assert isinstance(GeminiAdapter("gemini-2.5-pro", api_key="k"), LLMPort)

    def test_model_id_is_the_configured_model(self) -> None:
        assert GeminiAdapter("gemini-2.5-pro", api_key="k").model_id == "gemini-2.5-pro"


class TestRequestShape:
    def test_sends_contents_with_roles_mapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            captured["payload"] = payload
            return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(
                    ChatMessage(role=ChatRole.USER, content="hello"),
                    ChatMessage(role=ChatRole.ASSISTANT, content="hi there"),
                )
            )
        )
        assert captured["path"] == "/models/gemini-2.5-pro:generateContent"
        assert captured["payload"]["contents"] == [
            {"role": "user", "parts": [{"text": "hello"}]},
            {"role": "model", "parts": [{"text": "hi there"}]},
        ]

    def test_tool_role_maps_to_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        adapter.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.TOOL, content="4", name="add"),))
        )
        assert captured["payload"]["contents"] == [{"role": "user", "parts": [{"text": "4"}]}]

    def test_system_messages_become_system_instruction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(
                    ChatMessage(role=ChatRole.SYSTEM, content="Be terse."),
                    ChatMessage(role=ChatRole.USER, content="hi"),
                )
            )
        )
        assert captured["payload"]["systemInstruction"] == {"parts": [{"text": "Be terse."}]}
        assert captured["payload"]["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]

    def test_generation_config_nests_temperature_and_max_output_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="hi"),),
                max_tokens=256,
                temperature=0.2,
            )
        )
        assert captured["payload"]["generationConfig"]["temperature"] == 0.2
        assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 256

    def test_response_schema_maps_to_generation_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        schema: dict[str, object] = {"type": "object"}
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="hi"),), response_schema=schema
            )
        )
        assert captured["payload"]["generationConfig"]["responseMimeType"] == "application/json"
        assert captured["payload"]["generationConfig"]["responseSchema"] == schema

    def test_tools_wrap_all_declarations_in_one_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        tool_a = ToolSpec(name="add", description="Add", parameters_schema={"type": "object"})
        tool_b = ToolSpec(name="sub", description="Subtract", parameters_schema={"type": "object"})
        adapter.complete(
            CompletionRequest(
                messages=(ChatMessage(role=ChatRole.USER, content="2+2"),), tools=(tool_a, tool_b)
            )
        )
        assert captured["payload"]["tools"] == [
            {
                "functionDeclarations": [
                    {"name": "add", "description": "Add", "parameters": {"type": "object"}},
                    {"name": "sub", "description": "Subtract", "parameters": {"type": "object"}},
                ]
            }
        ]

    def test_api_key_is_sent_as_query_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_urlopen(request: Any, timeout: float) -> Any:
            captured["url"] = request.full_url

            class _Resp:
                def __enter__(self) -> _Resp:
                    return self

                def __exit__(self, *_args: object) -> None:
                    return None

                def read(self) -> bytes:
                    return b'{"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}'

            return _Resp()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="my-secret-key")
        adapter.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert "key=my-secret-key" in captured["url"]


class TestResponseMapping:
    def test_extracts_text_and_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Hello!"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3},
            }

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        result = GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text == "Hello!"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 3
        assert result.model == "gemini-2.5-pro"
        assert result.stop_reason == "stop"

    def test_parses_function_call_parts_with_args_already_a_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"functionCall": {"name": "add", "args": {"a": 2, "b": 3}}}]
                        }
                    }
                ]
            }

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        result = GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="2+3"),))
        )
        assert result.text is None
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.id == "call_0"
        assert call.name == "add"
        assert call.arguments == {"a": 2, "b": 3}

    @pytest.mark.parametrize(
        "malformed_parts",
        [
            ["not-a-dict"],
            [{"functionCall": "not-a-dict"}],
            [{"functionCall": {"name": 123, "args": {}}}],
            [{"functionCall": {"name": "add", "args": "not-a-dict"}}],
        ],
    )
    def test_malformed_parts_are_tolerated(
        self, monkeypatch: pytest.MonkeyPatch, malformed_parts: list[object]
    ) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"candidates": [{"content": {"parts": malformed_parts}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        result = GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text is None
        assert result.tool_calls == ()

    def test_missing_candidates_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        with pytest.raises(GeminiError, match="candidates"):
            GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_empty_candidates_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"candidates": []}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        with pytest.raises(GeminiError, match="candidates"):
            GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_malformed_candidate_entry_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"candidates": ["not-a-dict"]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        with pytest.raises(GeminiError, match="malformed candidate"):
            GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_missing_content_parts_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"candidates": [{"content": {}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        with pytest.raises(GeminiError, match=r"content\.parts"):
            GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_missing_usage_and_finish_reason_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: GeminiAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        monkeypatch.setattr(GeminiAdapter, "_post", _fake_post)
        result = GeminiAdapter("gemini-2.5-pro", api_key="k").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        assert result.stop_reason == "stop"


class TestPostErrorHandling:
    def test_connection_failure_raises_gemini_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k", base_url="http://localhost:1")
        with pytest.raises(GeminiError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_invalid_json_response_raises_gemini_error(
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
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        with pytest.raises(GeminiError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )


class TestCostAndTokenEstimates:
    def test_cost_estimate_raises_not_implemented(self) -> None:
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        with pytest.raises(NotImplementedError):
            adapter.cost_estimate(TokenUsage(prompt_tokens=1, completion_tokens=1))

    def test_count_tokens_is_a_rough_heuristic(self) -> None:
        adapter = GeminiAdapter("gemini-2.5-pro", api_key="k")
        assert adapter.count_tokens("") == 0
        assert adapter.count_tokens("hi") == 1
