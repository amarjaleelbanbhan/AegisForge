"""Conformance test for the LLM and Embedding ports."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from aegisforge.ports import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    EmbeddingPort,
    EmbeddingResult,
    LLMPort,
    TokenUsage,
)

pytestmark = pytest.mark.unit


class _FakeLLM:
    model_id = "fake-local-1b"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        prompt_tokens = sum(self.count_tokens(m.content) for m in request.messages)
        return CompletionResult(
            text="ok",
            usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=1),
            model=self.model_id,
            stop_reason="end_turn",
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def cost_estimate(self, usage: TokenUsage) -> float:
        return usage.total_tokens * 0.0

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=tuple((float(len(t)),) for t in texts),
            usage=TokenUsage(prompt_tokens=sum(len(t) for t in texts), completion_tokens=0),
            model=self.model_id,
        )


def test_fake_llm_satisfies_both_protocols() -> None:
    llm = _FakeLLM()
    assert isinstance(llm, LLMPort)
    assert isinstance(llm, EmbeddingPort)


def test_complete_reports_usage() -> None:
    request = CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hello world"),))
    result = _FakeLLM().complete(request)
    assert result.text == "ok"
    assert result.usage.total_tokens == 3
    assert result.usage.prompt_tokens == 2


def test_temperature_defaults_to_zero_for_reproducibility() -> None:
    request = CompletionRequest(messages=(ChatMessage(role=ChatRole.USER, content="hi"),))
    assert request.temperature == 0.0


def test_embed_returns_one_vector_per_text() -> None:
    result = _FakeLLM().embed(["a", "bb", "ccc"])
    assert len(result.vectors) == 3
