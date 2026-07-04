"""LLM port: the owned model abstraction (MPS §14, ADR-0006).

No AegisForge capability may depend on a single provider. Concrete adapters
(Anthropic, OpenAI, Gemini, Ollama, an OpenAI-compatible gateway, or LiteLLM
as a catch-all) each implement :class:`LLMPort`; nothing above this port
imports a provider SDK type. Every call returns :class:`TokenUsage` so cost
and token accounting can be recorded on the run manifest (MPS §5).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from aegisforge.ports._base import PortModel


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(PortModel):
    """One message in a conversation passed to an LLM.

    Untrusted content (source code, comments, repository text) MUST be
    carried as clearly-delimited data within a message's ``content``, never
    concatenated into a system/instruction message (ADR-0004).
    """

    role: ChatRole
    content: str
    name: str | None = None
    """Tool name, when ``role`` is ``TOOL``."""


class ToolSpec(PortModel):
    """A tool an LLM may call, described as a JSON-schema function."""

    name: str
    description: str
    parameters_schema: dict[str, object]


class ToolCall(PortModel):
    """A model's request to invoke a tool, to be executed by the caller."""

    id: str
    name: str
    arguments: dict[str, object]


class TokenUsage(PortModel):
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class CompletionRequest(PortModel):
    """A structured request to an :class:`LLMPort` adapter."""

    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...] = ()
    temperature: float = 0.0
    """Structured/decision tasks default to 0 for reproducibility (MPS NFR-1)."""
    max_tokens: int | None = None
    response_schema: dict[str, object] | None = None
    """JSON schema the response must conform to, for structured output."""


class CompletionResult(PortModel):
    """The outcome of one :meth:`LLMPort.complete` call."""

    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage
    model: str
    stop_reason: str


@runtime_checkable
class LLMPort(Protocol):
    """A language-model backend: one interchangeable adapter behind the port.

    No capability in AegisForge may require a specific implementation of this
    protocol; the model routing layer (MPS §14) selects an adapter per task
    class and records the chosen model + version on the run manifest.
    """

    @property
    def model_id(self) -> str:
        """The concrete model identifier this adapter is bound to."""
        ...

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Produce a single completion for ``request``."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate the token count of ``text`` for this model's tokenizer."""
        ...

    def cost_estimate(self, usage: TokenUsage) -> float:
        """Estimate the USD cost of ``usage`` for this model."""
        ...


class EmbeddingResult(PortModel):
    vectors: tuple[tuple[float, ...], ...]
    usage: TokenUsage
    model: str


@runtime_checkable
class EmbeddingPort(Protocol):
    """A text-embedding backend, used for retrieval (MPS §15 memory tiers)."""

    @property
    def model_id(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed ``texts``, returning one vector per input in the same order."""
        ...
