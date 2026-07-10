"""An `LLMPort` adapter for the OpenAI Chat Completions API shape (MPS §14).

Covers every provider that speaks the same `/v1/chat/completions` schema
OpenAI defined and the ecosystem standardized on: native **OpenAI**, plus
**Groq**, **OpenRouter**, **LM Studio**, and self-hosted **vLLM** servers —
all configured purely via `base_url`, with no provider-specific branching
in this module. This is what MPS §14 calls the "OpenAI-compatible" adapter
("covers vLLM + most gateways").

**Not live-verified.** This environment has no API key for any of these
providers. The request/response mapping below is written against OpenAI's
published, stable Chat Completions schema and is unit-tested against that
documented shape (deterministic, no network) — but unlike `OllamaAdapter`
(genuinely exercised against a live local server), nothing here has been
confirmed against a real response. Treat this as a reference implementation
to validate against a real account before depending on it in production.

Estimating cost (`cost_estimate`) needs a real, provider-specific price
table this codebase doesn't maintain yet (prices vary by model and change
over time); returning `0.0` unconditionally would misrepresent a paid
provider as free, which is worse than being honest that the estimate isn't
implemented. `cost_estimate` therefore raises `NotImplementedError` here,
clearly, rather than returning a silently wrong number.
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

_REQUEST_TIMEOUT_SECONDS = 120
_CHARS_PER_TOKEN_ESTIMATE = 4


class OpenAICompatibleError(RuntimeError):
    """Raised when the configured server can't be reached or returns an
    unusable response."""


def _message_payload(message: ChatMessage) -> dict[str, object]:
    payload: dict[str, object] = {"role": message.role.value, "content": message.content}
    if message.name is not None:
        payload["name"] = message.name
    return payload


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
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue
        call_id = raw_call.get("id")
        function = raw_call.get("function")
        if not isinstance(call_id, str) or not isinstance(function, dict):
            continue
        name = function.get("name")
        raw_arguments = function.get("arguments")
        if not isinstance(name, str) or not isinstance(raw_arguments, str):
            continue
        try:
            arguments = json.loads(raw_arguments)
        except ValueError:
            continue
        if not isinstance(arguments, dict):
            continue
        calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    return tuple(calls)


class OpenAICompatibleAdapter:
    """`LLMPort` adapter for any server speaking the OpenAI chat-completions API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def model_id(self) -> str:
        return self._model

    def complete(self, request: CompletionRequest) -> CompletionResult:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [_message_payload(message) for message in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": request.response_schema},
            }

        response = self._post("/chat/completions", payload)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenAICompatibleError(f"response has no 'choices': {response!r}")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise OpenAICompatibleError(f"malformed choice entry: {first_choice!r}")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise OpenAICompatibleError(f"choice missing 'message': {first_choice!r}")
        content = message.get("content")
        raw_usage = response.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return CompletionResult(
            text=content if isinstance(content, str) and content else None,
            tool_calls=_tool_calls_from(message),
            usage=TokenUsage(
                prompt_tokens=_as_int(usage.get("prompt_tokens")),
                completion_tokens=_as_int(usage.get("completion_tokens")),
            ),
            model=str(response.get("model", self._model)),
            stop_reason=str(first_choice.get("finish_reason", "stop")),
        )

    def count_tokens(self, text: str) -> int:
        """A rough ~4-chars-per-token estimate.

        A precise count needs the model's real tokenizer (e.g. `tiktoken`
        for OpenAI models specifically) — out of scope here since this
        adapter must stay usable for *any* OpenAI-compatible server,
        including ones running entirely different model families whose
        tokenizer `tiktoken` doesn't know about.
        """
        if not text:
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)

    def cost_estimate(self, usage: TokenUsage) -> float:
        raise NotImplementedError(
            "OpenAICompatibleAdapter has no maintained per-model price table; "
            "returning 0.0 would misrepresent a paid provider as free"
        )

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        # Fixed base URL from this adapter's own config, never user input
        # from the analyzed project.
        request = urllib.request.Request(  # noqa: S310 # nosec B310
            url, data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
                return dict(json.loads(response.read()))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise OpenAICompatibleError(f"request to {url} failed: {exc}") from exc


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["OpenAICompatibleAdapter", "OpenAICompatibleError"]
