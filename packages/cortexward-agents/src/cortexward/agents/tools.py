"""The tool-invocation loop: drives an `LLMPort` through a tool-calling round trip.

Given a `CompletionRequest` with `tools` populated and a registry mapping
tool name → callable, `run_tool_loop` sends the request, and for as long as
the model responds with `tool_calls` (rather than a final text answer),
executes each requested tool, appends its result as a `TOOL`-role
`ChatMessage`, and sends the extended conversation back — up to
`max_iterations` round trips, after which it returns whatever the model
last produced rather than looping forever on a model that never stops
calling tools.

Not every `LLMPort` backend actually returns structured `tool_calls` — see
`cortexward-llm`'s `OllamaAdapter` docstring: some local models emit a
tool-call *intent* as plain JSON text instead of the structured field. This
loop only recognizes `CompletionResult.tool_calls` as already defined by
the port; it simply returns a text-only result unchanged when a model never
populates that field. That is a property of the model/adapter, not a
limitation of this loop.

A tool that raises is *not* caught here (only an unregistered tool name
is) — a tool's own implementation bug is a real programming error that
should surface immediately, not be silently rewritten into a confusing
message for the model to misinterpret.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from cortexward.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    LLMPort,
    ToolCall,
)

ToolFunction = Callable[[Mapping[str, object]], object]


class ToolExecutionError(RuntimeError):
    """Raised when a tool call names a tool that isn't registered."""


def _execute_tool_call(call: ToolCall, tools: Mapping[str, ToolFunction]) -> str:
    tool = tools.get(call.name)
    if tool is None:
        raise ToolExecutionError(f"model requested unregistered tool {call.name!r}")
    result = tool(call.arguments)
    return result if isinstance(result, str) else json.dumps(result)


def run_tool_loop(
    llm: LLMPort,
    request: CompletionRequest,
    *,
    tools: Mapping[str, ToolFunction],
    max_iterations: int = 5,
) -> CompletionResult:
    """Drives `llm` through up to `max_iterations` tool-calling round trips."""
    messages = list(request.messages)
    result = llm.complete(request)
    for _ in range(max_iterations):
        if not result.tool_calls:
            return result
        messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=result.text or ""))
        for call in result.tool_calls:
            output = _execute_tool_call(call, tools)
            messages.append(ChatMessage(role=ChatRole.TOOL, content=output, name=call.name))
        request = CompletionRequest(
            messages=tuple(messages),
            tools=request.tools,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_schema=request.response_schema,
        )
        result = llm.complete(request)
    return result


__all__ = ["ToolExecutionError", "ToolFunction", "run_tool_loop"]
