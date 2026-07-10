"""An `LLMPort` adapter for Ollama's local HTTP API (MPS §14).

Ollama runs entirely on-device (default `http://localhost:11434`) and needs
no API key — one of the MPS's six required v1 adapters (native Anthropic,
native OpenAI, Gemini, Ollama, OpenAI-compatible, LiteLLM), and notably the
only one buildable and genuinely integration-testable in an environment
without provider credentials.

Invoked via stdlib `urllib` (no new HTTP-client dependency), mirroring
`cortexward.scanners.osv_scanner`'s approach. A connection failure raises
`OllamaError` rather than degrading silently — unlike a scanner (where one
unreachable data source shouldn't abort a whole scan), a caller invoking an
LLM adapter is relying on getting a real completion back; masking that
failure as "no result" would be actively misleading.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from cortexward.ports import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    TokenUsage,
    ToolCall,
    ToolSpec,
)

_DEFAULT_BASE_URL = "http://localhost:11434"
_REQUEST_TIMEOUT_SECONDS = 120
_CHARS_PER_TOKEN_ESTIMATE = 4
"""A rough English-text heuristic; Ollama exposes no standalone tokenizer
endpoint to compute this precisely without an actual completion call."""


class OllamaError(RuntimeError):
    """Raised when the local Ollama server can't be reached or returns an
    unusable response."""


def _message_payload(message: ChatMessage) -> dict[str, object]:
    return {"role": message.role.value, "content": message.content}


def _tool_payload(tool: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema,
        },
    }


def _tool_calls_from(raw_message: dict[str, Any]) -> tuple[ToolCall, ...]:
    raw_calls = raw_message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return ()
    calls: list[ToolCall] = []
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, dict):
            continue
        calls.append(
            ToolCall(id=str(raw_call.get("id", f"call_{index}")), name=name, arguments=arguments)
        )
    return tuple(calls)


class OllamaAdapter:
    """`LLMPort` adapter calling a local Ollama server's `/api/chat` endpoint."""

    def __init__(self, model: str, *, base_url: str = _DEFAULT_BASE_URL) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def model_id(self) -> str:
        return self._model

    def complete(self, request: CompletionRequest) -> CompletionResult:
        options: dict[str, object] = {"temperature": request.temperature}
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [_message_payload(message) for message in request.messages],
            "stream": False,
            "options": options,
        }
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]
        if request.response_schema is not None:
            payload["format"] = request.response_schema

        response = self._post("/api/chat", payload)
        message = response.get("message")
        if not isinstance(message, dict):
            raise OllamaError(f"Ollama response missing 'message': {response!r}")
        content = message.get("content")
        return CompletionResult(
            text=content if isinstance(content, str) and content else None,
            tool_calls=_tool_calls_from(message),
            usage=TokenUsage(
                prompt_tokens=_as_int(response.get("prompt_eval_count")),
                completion_tokens=_as_int(response.get("eval_count")),
            ),
            model=str(response.get("model", self._model)),
            stop_reason=str(response.get("done_reason", "stop")),
        )

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)

    def cost_estimate(self, usage: TokenUsage) -> float:
        """Always zero: Ollama runs entirely locally, with no per-token billing."""
        return 0.0

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        # Fixed local Ollama base URL from this adapter's own config, never
        # user input from the analyzed project.
        request = urllib.request.Request(  # noqa: S310 # nosec B310
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
                return dict(json.loads(response.read()))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise OllamaError(f"Ollama request to {url} failed: {exc}") from exc


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["OllamaAdapter", "OllamaError"]
