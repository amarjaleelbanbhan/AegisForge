"""Cost-aware model routing: task class → model tier → `LLMPort` (MPS §14).

MPS §14 specifies a **declarative router** mapping *task class* to *model
tier*:

| Task class          | Default tier | Rationale             |
|----------------------|--------------|------------------------|
| Triage / classification / dedup      | cheap  | high volume            |
| Reasoning / detection / threat model | strong | quality-critical       |
| Patch generation                     | strong | correctness-critical   |

Routing is **config-driven and overridable per run** (`tier_overrides`), and
**local/offline mode pins every task to local models** (`offline=True` pins
every `TaskClass` to `ModelTier.CHEAP` — CortexWard's designated local tier
— regardless of the default or overridden mapping). The chosen model's
identity is already carried on `CompletionResult.model` / `LLMPort.model_id`
for `RunManifest` recording; the router's only job is *selecting* an
adapter, not recording the choice.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from cortexward.ports import LLMPort


class TaskClass(StrEnum):
    """A category of LLM-backed work, each routed to an appropriate tier."""

    TRIAGE = "triage"
    REASONING = "reasoning"
    PATCH_GENERATION = "patch_generation"


class ModelTier(StrEnum):
    """A cost/capability class of model, config-mapped to a concrete adapter."""

    CHEAP = "cheap"
    STRONG = "strong"


_DEFAULT_TIER_BY_TASK: dict[TaskClass, ModelTier] = {
    TaskClass.TRIAGE: ModelTier.CHEAP,
    TaskClass.REASONING: ModelTier.STRONG,
    TaskClass.PATCH_GENERATION: ModelTier.STRONG,
}


class UnroutableTaskError(LookupError):
    """Raised when no adapter is registered for the tier a task routes to."""


class ModelRouter:
    """Routes a `TaskClass` to an `LLMPort` adapter by a declarative tier mapping."""

    def __init__(
        self,
        *,
        adapters: Mapping[ModelTier, LLMPort],
        tier_overrides: Mapping[TaskClass, ModelTier] | None = None,
        offline: bool = False,
    ) -> None:
        self._adapters = dict(adapters)
        self._tier_by_task: dict[TaskClass, ModelTier] = {
            **_DEFAULT_TIER_BY_TASK,
            **(tier_overrides or {}),
        }
        self._offline = offline

    def tier_for(self, task_class: TaskClass) -> ModelTier:
        """The tier `task_class` currently routes to (before adapter lookup)."""
        if self._offline:
            return ModelTier.CHEAP
        return self._tier_by_task[task_class]

    def route(self, task_class: TaskClass) -> LLMPort:
        """The `LLMPort` adapter `task_class` routes to.

        Raises `UnroutableTaskError` if no adapter is registered for the
        resolved tier — a missing adapter is a configuration error the
        caller must fix, not something to silently fall back from.
        """
        tier = self.tier_for(task_class)
        adapter = self._adapters.get(tier)
        if adapter is None:
            raise UnroutableTaskError(
                f"no LLMPort adapter registered for tier {tier!r} "
                f"(task class {task_class!r} routes to it)"
            )
        return adapter
