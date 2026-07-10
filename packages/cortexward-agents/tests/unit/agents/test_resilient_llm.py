"""Unit tests for `ResilientLLM` (retry/fallback)."""

from __future__ import annotations

import pytest

from cortexward.agents import AllAdaptersFailedError, ResilientLLM
from cortexward.ports import ChatMessage, ChatRole, CompletionRequest, CompletionResult, TokenUsage

pytestmark = pytest.mark.unit


class _FakeLLM:
    """A fake LLMPort that fails a configurable number of times, then succeeds."""

    def __init__(self, model_id: str, *, fail_times: int = 0, always_fail: bool = False) -> None:
        self.model_id = model_id
        self._fail_times = fail_times
        self._always_fail = always_fail
        self.call_count = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.call_count += 1
        if self._always_fail or self.call_count <= self._fail_times:
            raise RuntimeError(f"{self.model_id} failed (call {self.call_count})")
        return CompletionResult(
            text=f"ok from {self.model_id}",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            model=self.model_id,
            stop_reason="end_turn",
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def cost_estimate(self, usage: TokenUsage) -> float:
        return usage.total_tokens * 0.0


def _request() -> CompletionRequest:
    return CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))


def _no_sleep(_seconds: float) -> None:
    return None


class TestConstruction:
    def test_rejects_an_empty_adapter_list(self) -> None:
        with pytest.raises(ValueError, match="at least one adapter"):
            ResilientLLM([])

    def test_model_id_reflects_the_primary_adapter(self) -> None:
        resilient = ResilientLLM([_FakeLLM("primary"), _FakeLLM("fallback")], sleep=_no_sleep)
        assert resilient.model_id == "primary"


class TestRetry:
    def test_succeeds_immediately_when_the_adapter_works(self) -> None:
        primary = _FakeLLM("primary")
        resilient = ResilientLLM([primary], sleep=_no_sleep)
        result = resilient.complete(_request())
        assert result.text == "ok from primary"
        assert primary.call_count == 1

    def test_retries_a_failing_adapter_before_giving_up(self) -> None:
        primary = _FakeLLM("primary", fail_times=2)
        resilient = ResilientLLM([primary], max_retries=2, sleep=_no_sleep)
        result = resilient.complete(_request())
        assert result.text == "ok from primary"
        assert primary.call_count == 3

    def test_exhausting_retries_on_a_single_adapter_raises(self) -> None:
        primary = _FakeLLM("primary", always_fail=True)
        resilient = ResilientLLM([primary], max_retries=1, sleep=_no_sleep)
        with pytest.raises(AllAdaptersFailedError):
            resilient.complete(_request())
        assert primary.call_count == 2  # initial attempt + 1 retry

    def test_sleep_is_called_with_increasing_backoff(self) -> None:
        sleeps: list[float] = []
        primary = _FakeLLM("primary", fail_times=2)
        resilient = ResilientLLM([primary], max_retries=2, backoff_seconds=1.0, sleep=sleeps.append)
        resilient.complete(_request())
        assert sleeps == [1.0, 2.0]


class TestFallback:
    def test_falls_back_to_the_second_adapter_after_the_first_exhausts_retries(self) -> None:
        primary = _FakeLLM("primary", always_fail=True)
        fallback = _FakeLLM("fallback")
        resilient = ResilientLLM([primary, fallback], max_retries=1, sleep=_no_sleep)
        result = resilient.complete(_request())
        assert result.text == "ok from fallback"
        assert primary.call_count == 2
        assert fallback.call_count == 1

    def test_all_adapters_failing_raises_with_every_error_recorded(self) -> None:
        primary = _FakeLLM("primary", always_fail=True)
        fallback = _FakeLLM("fallback", always_fail=True)
        resilient = ResilientLLM([primary, fallback], max_retries=0, sleep=_no_sleep)
        with pytest.raises(AllAdaptersFailedError) as exc_info:
            resilient.complete(_request())
        assert "primary" in str(exc_info.value)
        assert "fallback" in str(exc_info.value)

    def test_does_not_sleep_after_the_final_failed_attempt_on_the_last_adapter(self) -> None:
        sleeps: list[float] = []
        primary = _FakeLLM("primary", always_fail=True)
        resilient = ResilientLLM([primary], max_retries=0, sleep=sleeps.append)
        with pytest.raises(AllAdaptersFailedError):
            resilient.complete(_request())
        assert sleeps == []


class TestDelegatedMethods:
    def test_count_tokens_delegates_to_the_primary_adapter(self) -> None:
        resilient = ResilientLLM([_FakeLLM("primary")], sleep=_no_sleep)
        assert resilient.count_tokens("hello world") == 2

    def test_cost_estimate_delegates_to_the_primary_adapter(self) -> None:
        resilient = ResilientLLM([_FakeLLM("primary")], sleep=_no_sleep)
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        assert resilient.cost_estimate(usage) == 0.0
