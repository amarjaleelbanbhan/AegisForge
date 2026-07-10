"""`ResilientLLM`: a retrying, falling-back `LLMPort` wrapper (MPS §14).

Wraps an ordered sequence of `LLMPort` adapters. Each `complete()` call
tries the first adapter up to `max_retries` times (exponential backoff
between attempts), and on exhausting retries moves to the next adapter in
the sequence. This is what lets an agent's own code stay oblivious to a
transient backend hiccup, or a whole provider being briefly unreachable —
the caller sees one `LLMPort`, not a provider-selection decision tree.

Deliberately catches every `Exception` a wrapped adapter raises, not a
provider-specific error type: adapters for different providers (Ollama,
OpenAI, Anthropic, Gemini, ...) each surface failures through their own
exception hierarchies, and a resilience wrapper that only knew about one
provider's exceptions would silently stop retrying for every other one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from cortexward.ports import CompletionRequest, CompletionResult, LLMPort, TokenUsage


class AllAdaptersFailedError(RuntimeError):
    """Raised when every configured adapter failed on every retry attempt."""


class ResilientLLM:
    """An `LLMPort` that retries transient failures and falls back across adapters."""

    def __init__(
        self,
        adapters: Sequence[LLMPort],
        *,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not adapters:
            raise ValueError("ResilientLLM needs at least one adapter")
        self._adapters = tuple(adapters)
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    @property
    def model_id(self) -> str:
        """The primary (first) adapter's model id.

        Reflects what would actually be used absent any failures; a caller
        wanting to know which adapter *actually* answered a given
        `complete()` call should read `CompletionResult.model` instead.
        """
        return self._adapters[0].model_id

    def complete(self, request: CompletionRequest) -> CompletionResult:
        errors: list[Exception] = []
        for adapter_index, adapter in enumerate(self._adapters):
            for attempt in range(self._max_retries + 1):
                try:
                    return adapter.complete(request)
                except Exception as exc:
                    errors.append(exc)
                    is_last_attempt_for_adapter = attempt == self._max_retries
                    is_last_adapter = adapter_index == len(self._adapters) - 1
                    if not (is_last_attempt_for_adapter and is_last_adapter):
                        self._sleep(self._backoff_seconds * (2**attempt))
        raise AllAdaptersFailedError(
            f"all {len(self._adapters)} adapter(s) failed after retries: "
            f"{'; '.join(str(error) for error in errors)}"
        ) from errors[-1]

    def count_tokens(self, text: str) -> int:
        return self._adapters[0].count_tokens(text)

    def cost_estimate(self, usage: TokenUsage) -> float:
        return self._adapters[0].cost_estimate(usage)


__all__ = ["AllAdaptersFailedError", "ResilientLLM"]
