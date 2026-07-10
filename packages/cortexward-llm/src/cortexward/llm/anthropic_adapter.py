"""An `LLMPort` adapter for Anthropic's Messages API (MPS §14).

**Not live-verified.** This environment has no Anthropic API key. The
request/response mapping below is written against Anthropic's published,
stable Messages API schema and is unit-tested against that documented
shape (deterministic, no network) — but unlike `OllamaAdapter` (genuinely
exercised against a live local server), nothing here has been confirmed
against a real response. Treat this as a reference implementation to
validate against a real account before depending on it in production.

Two shape differences from the OpenAI-style adapters in this package are
load-bearing, not incidental:

- **`system` is a top-level request field, not a message.** Anthropic
  rejects a `role: "system"` entry inside `messages`; any `ChatMessage`
  with `role=SYSTEM` is extracted and concatenated into `system` instead.
- **`max_tokens` is required**, with no server-side default — a request
  that leaves it unset gets `_DEFAULT_MAX_TOKENS` here rather than omitting
  the field and letting the API reject the call.
- **Response `content` is a list of typed blocks** (`text` / `tool_use`),
  not a single string plus a separate `tool_calls` array — this adapter
  concatenates every `text` block into `CompletionResult.text` and maps
  every `tool_use` block into a `ToolCall`.

As with `OpenAICompatibleAdapter`, `cost_estimate` raises rather than
silently returning `0.0`: this codebase doesn't maintain a per-model
Anthropic price table, and misreporting a paid API as free is worse than
being explicit that the estimate isn't implemented.
"""

from __future__ import annotations

import json
import urllib.error
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
_DEFAULT_MAX_TOKENS = 4096
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicError(RuntimeError):
    """Raised when the Anthropic API can't be reached or returns an
    unusable response."""


def _split_system(messages: tuple[ChatMessage, ...]) -> tuple[str | None, list[ChatMessage]]:
    system_parts = [m.content for m in messages if m.role == ChatRole.SYSTEM]
    remaining = [m for m in messages if m.role != ChatRole.SYSTEM]
    system = "\n\n".join(system_parts) if system_parts else None
    return system, remaining


def _message_payload(message: ChatMessage) -> dict[str, object]:
    # Anthropic has no distinct TOOL role; a tool result is a user-turn
    # content block in the real API. This adapter maps a ChatRole.TOOL
    # message onto role="user" so a tool-calling round trip degrades to a
    # plain follow-up turn rather than being silently dropped.
    role = "assistant" if message.role == ChatRole.ASSISTANT else "user"
    return {"role": role, "content": message.content}


def _tool_payload(tool: ToolSpec) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters_schema,
    }


def _text_and_tool_calls(blocks: list[Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif block_type == "tool_use":
            call_id = block.get("id")
            name = block.get("name")
            tool_input = block.get("input")
            if isinstance(call_id, str) and isinstance(name, str) and isinstance(tool_input, dict):
                calls.append(ToolCall(id=call_id, name=name, arguments=tool_input))
    text = "".join(text_parts) if text_parts else None
    return text, tuple(calls)


class AnthropicAdapter:
    """`LLMPort` adapter for Anthropic's Messages API (`/v1/messages`)."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def model_id(self) -> str:
        return self._model

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system, remaining_messages = _split_system(request.messages)
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [_message_payload(message) for message in remaining_messages],
            "max_tokens": request.max_tokens or _DEFAULT_MAX_TOKENS,
            "temperature": request.temperature,
        }
        if system is not None:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]

        response = self._post("/messages", payload)
        content = response.get("content")
        if not isinstance(content, list):
            raise AnthropicError(f"response has no 'content' list: {response!r}")
        text, tool_calls = _text_and_tool_calls(content)
        raw_usage = response.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            usage=TokenUsage(
                prompt_tokens=_as_int(usage.get("input_tokens")),
                completion_tokens=_as_int(usage.get("output_tokens")),
            ),
            model=str(response.get("model", self._model)),
            stop_reason=str(response.get("stop_reason", "end_turn")),
        )

    def count_tokens(self, text: str) -> int:
        """A rough ~4-chars-per-token estimate.

        Anthropic offers a real `/v1/messages/count_tokens` endpoint, but
        using it would mean a network round trip for every token estimate
        (a synchronous `LLMPort.count_tokens` call is expected to be cheap
        and local, e.g. for pre-flight budget checks) — out of scope here.
        """
        if not text:
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)

    def cost_estimate(self, usage: TokenUsage) -> float:
        raise NotImplementedError(
            "AnthropicAdapter has no maintained per-model price table; "
            "returning 0.0 would misrepresent a paid provider as free"
        )

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
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
            raise AnthropicError(f"request to {url} failed: {exc}") from exc


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["AnthropicAdapter", "AnthropicError"]
