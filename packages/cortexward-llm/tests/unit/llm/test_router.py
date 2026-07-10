"""Unit tests for the cost-aware model router."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from cortexward.llm import ModelRouter, ModelTier, TaskClass, UnroutableTaskError
from cortexward.ports import CompletionRequest, CompletionResult, EmbeddingResult, TokenUsage

pytestmark = pytest.mark.unit


class _FakeLLM:
    """A minimal, deterministic `LLMPort` — no network calls."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
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


class TestDefaultRouting:
    def test_triage_routes_to_the_cheap_tier(self) -> None:
        cheap = _FakeLLM("cheap-model")
        strong = _FakeLLM("strong-model")
        router = ModelRouter(adapters={ModelTier.CHEAP: cheap, ModelTier.STRONG: strong})
        assert router.route(TaskClass.TRIAGE) is cheap

    def test_reasoning_routes_to_the_strong_tier(self) -> None:
        cheap = _FakeLLM("cheap-model")
        strong = _FakeLLM("strong-model")
        router = ModelRouter(adapters={ModelTier.CHEAP: cheap, ModelTier.STRONG: strong})
        assert router.route(TaskClass.REASONING) is strong

    def test_patch_generation_routes_to_the_strong_tier(self) -> None:
        cheap = _FakeLLM("cheap-model")
        strong = _FakeLLM("strong-model")
        router = ModelRouter(adapters={ModelTier.CHEAP: cheap, ModelTier.STRONG: strong})
        assert router.route(TaskClass.PATCH_GENERATION) is strong

    def test_tier_for_reports_the_resolved_tier_without_needing_an_adapter(self) -> None:
        router = ModelRouter(adapters={})
        assert router.tier_for(TaskClass.TRIAGE) is ModelTier.CHEAP
        assert router.tier_for(TaskClass.REASONING) is ModelTier.STRONG


class TestOverrides:
    def test_a_tier_override_changes_routing_for_that_task_class_only(self) -> None:
        cheap = _FakeLLM("cheap-model")
        strong = _FakeLLM("strong-model")
        router = ModelRouter(
            adapters={ModelTier.CHEAP: cheap, ModelTier.STRONG: strong},
            tier_overrides={TaskClass.TRIAGE: ModelTier.STRONG},
        )
        assert router.route(TaskClass.TRIAGE) is strong
        assert router.route(TaskClass.REASONING) is strong  # unaffected default

    def test_overrides_do_not_mutate_the_default_mapping_across_instances(self) -> None:
        strong = _FakeLLM("strong-model")
        cheap = _FakeLLM("cheap-model")
        overridden = ModelRouter(
            adapters={ModelTier.STRONG: strong},
            tier_overrides={TaskClass.TRIAGE: ModelTier.STRONG},
        )
        fresh = ModelRouter(adapters={ModelTier.CHEAP: cheap, ModelTier.STRONG: strong})
        assert overridden.route(TaskClass.TRIAGE) is strong
        assert fresh.route(TaskClass.TRIAGE) is cheap


class TestOfflineMode:
    def test_offline_pins_every_task_class_to_the_cheap_tier(self) -> None:
        cheap = _FakeLLM("local-model")
        router = ModelRouter(adapters={ModelTier.CHEAP: cheap}, offline=True)
        assert router.route(TaskClass.TRIAGE) is cheap
        assert router.route(TaskClass.REASONING) is cheap
        assert router.route(TaskClass.PATCH_GENERATION) is cheap

    def test_offline_overrides_a_tier_override_too(self) -> None:
        cheap = _FakeLLM("local-model")
        strong = _FakeLLM("strong-model")
        router = ModelRouter(
            adapters={ModelTier.CHEAP: cheap, ModelTier.STRONG: strong},
            tier_overrides={TaskClass.TRIAGE: ModelTier.STRONG},
            offline=True,
        )
        assert router.route(TaskClass.TRIAGE) is cheap


class TestUnroutable:
    def test_missing_adapter_for_the_resolved_tier_raises(self) -> None:
        router = ModelRouter(adapters={ModelTier.CHEAP: _FakeLLM("cheap-model")})
        with pytest.raises(UnroutableTaskError, match="STRONG"):
            router.route(TaskClass.REASONING)

    def test_no_adapters_at_all_raises_for_every_task_class(self) -> None:
        router = ModelRouter(adapters={})
        with pytest.raises(UnroutableTaskError):
            router.route(TaskClass.TRIAGE)
