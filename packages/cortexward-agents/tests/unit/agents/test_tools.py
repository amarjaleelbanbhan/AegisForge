"""Unit tests for the tool-invocation loop."""

from __future__ import annotations

import pytest

from cortexward.agents import ToolExecutionError, run_tool_loop
from cortexward.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    TokenUsage,
    ToolCall,
)

pytestmark = pytest.mark.unit


def _request(**overrides: object) -> CompletionRequest:
    defaults: dict[str, object] = {"messages": (ChatMessage(role=ChatRole.USER, content="hi"),)}
    defaults.update(overrides)
    return CompletionRequest(**defaults)  # type: ignore[arg-type]


def _result(*, text: str | None, tool_calls: tuple[ToolCall, ...] = ()) -> CompletionResult:
    return CompletionResult(
        text=text,
        tool_calls=tool_calls,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
        model="fake-model",
        stop_reason="end_turn" if not tool_calls else "tool_calls",
    )


class _ScriptedLLM:
    """Replays a fixed sequence of `CompletionResult`s, one per `complete()` call."""

    def __init__(self, results: list[CompletionResult]) -> None:
        self.model_id = "fake-model"
        self._results = list(results)
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return self._results.pop(0)

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def cost_estimate(self, usage: TokenUsage) -> float:
        return usage.total_tokens * 0.0


class TestRunToolLoop:
    def test_returns_immediately_when_the_model_makes_no_tool_calls(self) -> None:
        llm = _ScriptedLLM([_result(text="final answer")])
        result = run_tool_loop(llm, _request(), tools={})
        assert result.text == "final answer"
        assert len(llm.requests) == 1

    def test_executes_a_single_tool_call_and_resends(self) -> None:
        call = ToolCall(id="call_1", name="add", arguments={"a": 2, "b": 3})
        llm = _ScriptedLLM([_result(text=None, tool_calls=(call,)), _result(text="the sum is 5")])
        tools = {"add": lambda args: args["a"] + args["b"]}
        result = run_tool_loop(llm, _request(), tools=tools)
        assert result.text == "the sum is 5"
        assert len(llm.requests) == 2
        # The second request carries the tool's result as a TOOL-role message.
        second_request_messages = llm.requests[1].messages
        tool_messages = [m for m in second_request_messages if m.role == ChatRole.TOOL]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "5"
        assert tool_messages[0].name == "add"

    def test_executes_multiple_tool_calls_in_one_round(self) -> None:
        calls = (
            ToolCall(id="c1", name="add", arguments={"a": 1, "b": 1}),
            ToolCall(id="c2", name="mul", arguments={"a": 2, "b": 2}),
        )
        llm = _ScriptedLLM([_result(text=None, tool_calls=calls), _result(text="done")])
        tools = {
            "add": lambda args: args["a"] + args["b"],
            "mul": lambda args: args["a"] * args["b"],
        }
        result = run_tool_loop(llm, _request(), tools=tools)
        assert result.text == "done"
        tool_messages = [m for m in llm.requests[1].messages if m.role == ChatRole.TOOL]
        assert {m.name for m in tool_messages} == {"add", "mul"}

    def test_a_tool_returning_a_non_string_is_json_encoded(self) -> None:
        call = ToolCall(id="c1", name="lookup", arguments={})
        llm = _ScriptedLLM([_result(text=None, tool_calls=(call,)), _result(text="ok")])
        tools = {"lookup": lambda _args: {"key": "value", "count": 3}}
        run_tool_loop(llm, _request(), tools=tools)
        tool_message = next(m for m in llm.requests[1].messages if m.role == ChatRole.TOOL)
        assert '"key": "value"' in tool_message.content

    def test_an_unregistered_tool_call_raises(self) -> None:
        call = ToolCall(id="c1", name="unknown", arguments={})
        llm = _ScriptedLLM([_result(text=None, tool_calls=(call,))])
        with pytest.raises(ToolExecutionError, match="unknown"):
            run_tool_loop(llm, _request(), tools={})

    def test_stops_after_max_iterations_even_if_still_calling_tools(self) -> None:
        call = ToolCall(id="c1", name="loop", arguments={})
        # The model calls a tool every single time -- 3 scripted rounds plus
        # the initial call, all returning further tool calls.
        llm = _ScriptedLLM([_result(text=None, tool_calls=(call,)) for _ in range(4)])
        tools = {"loop": lambda _args: "again"}
        result = run_tool_loop(llm, _request(), tools=tools, max_iterations=3)
        # Initial call + 3 iterations = 4 total complete() calls.
        assert len(llm.requests) == 4
        assert result.tool_calls == (call,)

    def test_conversation_history_accumulates_across_rounds(self) -> None:
        call = ToolCall(id="c1", name="add", arguments={"a": 1, "b": 1})
        llm = _ScriptedLLM([_result(text=None, tool_calls=(call,)), _result(text="done")])
        tools = {"add": lambda args: args["a"] + args["b"]}
        run_tool_loop(llm, _request(), tools=tools)
        final_request_messages = llm.requests[1].messages
        roles = [m.role for m in final_request_messages]
        assert roles == [ChatRole.USER, ChatRole.ASSISTANT, ChatRole.TOOL]
