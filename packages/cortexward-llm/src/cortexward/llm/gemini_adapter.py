"""An `LLMPort` adapter for Google's Gemini `generateContent` API (MPS §14).

**Not live-verified.** This environment has no Gemini API key. The
request/response mapping below is written against Google's published,
stable `generateContent` REST schema and is unit-tested against that
documented shape (deterministic, no network) — but unlike `OllamaAdapter`
(genuinely exercised against a live local server), nothing here has been
confirmed against a real response. Treat this as a reference implementation
to validate against a real account before depending on it in production.

Gemini's shape differs from both the OpenAI-style and Anthropic adapters
in this package in several load-bearing ways:

- The API key is a **query parameter** (`?key=...`), not an `Authorization`
  header.
- Turns are called `contents`, each with a `role` of `"user"` or `"model"`
  (never `"assistant"`) and a list of `parts` rather than a flat string.
- A system prompt is `systemInstruction`, a top-level field structured the
  same way as one `contents` entry — like Anthropic's `system`, it is
  never a message with a role.
- Generation parameters (`temperature`, `maxOutputTokens`) live under a
  nested `generationConfig` object, not top-level request fields.
- Tools are `functionDeclarations` nested inside a single `tools` array
  entry, and a tool call comes back as a `functionCall` part with `args`
  already parsed as an object (not a JSON-encoded string, unlike OpenAI's
  `tool_calls[].function.arguments`).

As with the other new adapters, `cost_estimate` raises rather than
silently returning `0.0`: this codebase doesn't maintain a per-model
Gemini price table.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cortexward.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    TokenUsage,
    ToolCall,
    ToolSpec,
)

_REQUEST_TIMEOUT_SECONDS = 120
_CHARS_PER_TOKEN_ESTIMATE = 4
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    """Raised when the Gemini API can't be reached or returns an unusable response."""


def _split_system(messages: tuple[ChatMessage, ...]) -> tuple[str | None, list[ChatMessage]]:
    system_parts = [m.content for m in messages if m.role == ChatRole.SYSTEM]
    remaining = [m for m in messages if m.role != ChatRole.SYSTEM]
    system = "\n\n".join(system_parts) if system_parts else None
    return system, remaining


def _content_payload(message: ChatMessage) -> dict[str, object]:
    # Gemini has no distinct TOOL role either; map it onto "user" the same
    # documented way `AnthropicAdapter` does, for the same reason.
    role = "model" if message.role == ChatRole.ASSISTANT else "user"
    return {"role": role, "parts": [{"text": message.content}]}


def _tool_payload(tools: tuple[ToolSpec, ...]) -> dict[str, object]:
    return {
        "functionDeclarations": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            }
            for tool in tools
        ]
    }


def _text_and_tool_calls(parts: list[Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
        function_call = part.get("functionCall")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            args = function_call.get("args")
            if isinstance(name, str) and isinstance(args, dict):
                calls.append(ToolCall(id=f"call_{index}", name=name, arguments=args))
    text = "".join(text_parts) if text_parts else None
    return text, tuple(calls)


class GeminiAdapter:
    """`LLMPort` adapter for Google's `models/{model}:generateContent` API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def model_id(self) -> str:
        return self._model

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system, remaining_messages = _split_system(request.messages)
        generation_config: dict[str, object] = {"temperature": request.temperature}
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.response_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = request.response_schema

        payload: dict[str, object] = {
            "contents": [_content_payload(message) for message in remaining_messages],
            "generationConfig": generation_config,
        }
        if system is not None:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if request.tools:
            payload["tools"] = [_tool_payload(request.tools)]

        response = self._post(f"/models/{self._model}:generateContent", payload)
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GeminiError(f"response has no 'candidates': {response!r}")
        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise GeminiError(f"malformed candidate entry: {first_candidate!r}")
        content = first_candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise GeminiError(f"candidate missing 'content.parts': {first_candidate!r}")
        text, tool_calls = _text_and_tool_calls(parts)
        raw_usage = response.get("usageMetadata")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            usage=TokenUsage(
                prompt_tokens=_as_int(usage.get("promptTokenCount")),
                completion_tokens=_as_int(usage.get("candidatesTokenCount")),
            ),
            model=self._model,
            stop_reason=str(first_candidate.get("finishReason", "STOP")).lower(),
        )

    def count_tokens(self, text: str) -> int:
        """A rough ~4-chars-per-token estimate.

        Gemini offers a real `countTokens` endpoint, but using it would
        mean a network round trip for every token estimate (a synchronous
        `LLMPort.count_tokens` call is expected to be cheap and local) —
        out of scope here, matching the same tradeoff `AnthropicAdapter`
        documents for its own `count_tokens` endpoint.
        """
        if not text:
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)

    def cost_estimate(self, usage: TokenUsage) -> float:
        raise NotImplementedError(
            "GeminiAdapter has no maintained per-model price table; "
            "returning 0.0 would misrepresent a paid provider as free"
        )

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        query = urllib.parse.urlencode({"key": self._api_key})
        url = f"{self._base_url}{path}?{query}"
        data = json.dumps(payload).encode("utf-8")
        # Fixed base URL from this adapter's own config, never user input
        # from the analyzed project.
        request = urllib.request.Request(  # noqa: S310 # nosec B310
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 # nosec B310
                return dict(json.loads(response.read()))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise GeminiError(f"request to {self._base_url}{path} failed: {exc}") from exc


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["GeminiAdapter", "GeminiError"]
