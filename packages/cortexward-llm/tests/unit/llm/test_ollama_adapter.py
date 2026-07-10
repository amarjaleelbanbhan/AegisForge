"""Unit tests for the Ollama LLMPort adapter.

Most tests monkeypatch the adapter's own `_post` so the request/response
mapping is exercised deterministically without any real server — the
adapter's logic (message/tool payload shaping, usage extraction, tool-call
parsing, error handling) is what's under test, not Ollama itself.

`TestLiveOllama` is the exception: it talks to a real local Ollama server
when one happens to be running (this project's CI has no Ollama installed —
unlike OSV.dev, a public service, Ollama here is local-only), and is skipped
otherwise. Confirms the adapter genuinely works end-to-end when the
environment allows it, consistent with this codebase's preference for real
integration tests over mocking wherever the target is actually reachable.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any
from urllib.error import URLError

import pytest

from cortexward.llm import OllamaAdapter, OllamaError
from cortexward.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMPort,
    TokenUsage,
    ToolSpec,
)

pytestmark = pytest.mark.unit

_LIVE_OLLAMA_URL = "http://localhost:11434"
_LIVE_MODEL = "qwen2.5-coder:7b"


def _ollama_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{_LIVE_OLLAMA_URL}/api/tags", timeout=2):  # noqa: S310 # nosec B310
            return True
    except (URLError, TimeoutError, OSError):
        return False


class TestProtocolConformance:
    def test_ollama_adapter_satisfies_the_port(self) -> None:
        assert isinstance(OllamaAdapter("test-model"), LLMPort)

    def test_model_id_is_the_configured_model(self) -> None:
        assert OllamaAdapter("qwen2.5-coder:7b").model_id == "qwen2.5-coder:7b"


class TestCostAndTokenEstimates:
    def test_cost_estimate_is_always_zero(self) -> None:
        adapter = OllamaAdapter("test-model")
        assert (
            adapter.cost_estimate(TokenUsage(prompt_tokens=10_000, completion_tokens=5_000)) == 0.0
        )

    def test_count_tokens_is_roughly_proportional_to_length(self) -> None:
        adapter = OllamaAdapter("test-model")
        assert adapter.count_tokens("") == 0
        assert adapter.count_tokens("hi") == 1
        assert adapter.count_tokens("a" * 400) > adapter.count_tokens("a" * 40)


class TestCompleteRequestShape:
    def test_sends_the_configured_model_and_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["path"] = path
            captured["payload"] = payload
            return {"model": self.model_id, "message": {"role": "assistant", "content": "hi"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        adapter = OllamaAdapter("qwen2.5-coder:7b")
        request = CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hello"),))
        adapter.complete(request)

        assert captured["path"] == "/api/chat"
        assert captured["payload"]["model"] == "qwen2.5-coder:7b"
        assert captured["payload"]["messages"] == [{"role": "user", "content": "hello"}]
        assert captured["payload"]["stream"] is False

    def test_includes_tools_when_the_request_has_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"message": {"role": "assistant", "content": "ok"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        adapter = OllamaAdapter("test-model")
        tool = ToolSpec(
            name="add", description="Add two numbers", parameters_schema={"type": "object"}
        )
        request = CompletionRequest(
            messages=(ChatMessage(role=ChatRole.USER, content="2+2"),), tools=(tool,)
        )
        adapter.complete(request)

        assert captured["payload"]["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {"type": "object"},
                },
            }
        ]

    def test_omits_tools_when_the_request_has_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"message": {"role": "assistant", "content": "ok"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        adapter = OllamaAdapter("test-model")
        adapter.complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert "tools" not in captured["payload"]

    def test_max_tokens_maps_to_num_predict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"message": {"role": "assistant", "content": "ok"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        adapter = OllamaAdapter("test-model")
        request = CompletionRequest(
            messages=(ChatMessage(role=ChatRole.USER, content="hi"),), max_tokens=256
        )
        adapter.complete(request)
        assert captured["payload"]["options"]["num_predict"] == 256

    def test_response_schema_maps_to_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            captured["payload"] = payload
            return {"message": {"role": "assistant", "content": "{}"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        adapter = OllamaAdapter("test-model")
        schema: dict[str, object] = {"type": "object", "properties": {"x": {"type": "integer"}}}
        request = CompletionRequest(
            messages=(ChatMessage(role=ChatRole.USER, content="hi"),), response_schema=schema
        )
        adapter.complete(request)
        assert captured["payload"]["format"] == schema


class TestCompleteResponseMapping:
    def test_extracts_text_and_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": "Hello!"},
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 3,
            }

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text == "Hello!"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 3
        assert result.model == "qwen2.5-coder:7b"
        assert result.stop_reason == "stop"

    def test_empty_content_maps_to_none_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"message": {"role": "assistant", "content": ""}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.text is None

    def test_missing_usage_fields_default_to_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"message": {"role": "assistant", "content": "ok"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0

    def test_missing_done_reason_defaults_to_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"message": {"role": "assistant", "content": "ok"}}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.stop_reason == "stop"

    def test_missing_message_raises_ollama_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"done": True}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        with pytest.raises(OllamaError, match="missing 'message'"):
            OllamaAdapter("test-model").complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_well_formed_tool_calls_are_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "add", "arguments": {"a": 2, "b": 2}},
                        }
                    ],
                }
            }

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="2+2"),))
        )
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.id == "call_1"
        assert call.name == "add"
        assert call.arguments == {"a": 2, "b": 2}

    def test_tool_call_missing_id_gets_a_generated_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "add", "arguments": {}}}],
                }
            }

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.tool_calls[0].id == "call_0"

    @pytest.mark.parametrize(
        "malformed_message",
        [
            {"role": "assistant", "content": "", "tool_calls": "not-a-list"},
            {"role": "assistant", "content": "", "tool_calls": [123]},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": 123, "arguments": {}}}],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "add", "arguments": "not-a-dict"}}],
            },
        ],
    )
    def test_malformed_tool_calls_are_tolerated_not_crashed_on(
        self, monkeypatch: pytest.MonkeyPatch, malformed_message: dict[str, Any]
    ) -> None:
        def _fake_post(
            self: OllamaAdapter, path: str, payload: dict[str, object]
        ) -> dict[str, Any]:
            return {"message": malformed_message}

        monkeypatch.setattr(OllamaAdapter, "_post", _fake_post)
        result = OllamaAdapter("test-model").complete(
            CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
        )
        assert result.tool_calls == ()


class TestPostErrorHandling:
    def test_connection_failure_raises_ollama_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        adapter = OllamaAdapter("test-model", base_url="http://localhost:1")
        with pytest.raises(OllamaError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )

    def test_invalid_json_response_raises_ollama_error(
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
        adapter = OllamaAdapter("test-model")
        with pytest.raises(OllamaError, match="failed"):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )


@pytest.mark.integration
@pytest.mark.skipif(not _ollama_is_running(), reason="no local Ollama server reachable")
class TestLiveOllama:
    """Genuinely exercises a local Ollama server end-to-end, when present.

    Not required for CI (which has no Ollama installed) — skipped there,
    exercised whenever a developer (or this environment) happens to be
    running one, per the module docstring.
    """

    def test_a_real_completion_round_trips(self) -> None:
        adapter = OllamaAdapter(_LIVE_MODEL, base_url=_LIVE_OLLAMA_URL)
        request = CompletionRequest(
            messages=(ChatMessage(role=ChatRole.USER, content="Reply with exactly: pong"),)
        )
        result = adapter.complete(request)
        assert result.text
        assert result.usage.prompt_tokens > 0
        assert result.model == _LIVE_MODEL

    def test_unreachable_port_raises_ollama_error(self) -> None:
        adapter = OllamaAdapter(_LIVE_MODEL, base_url="http://localhost:1")
        with pytest.raises(OllamaError):
            adapter.complete(
                CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
            )
