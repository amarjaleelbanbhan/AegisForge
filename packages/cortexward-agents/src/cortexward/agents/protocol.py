"""The `Agent` protocol: a stateless function over `RunState` (MPS §13)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cortexward.agents.state import RunState


@runtime_checkable
class Agent(Protocol):
    """One stage of the agent pipeline: state in, state out.

    Agents are deliberately not classes with hidden mutable run-scoped
    fields: everything that changes over the course of a run lives on the
    `RunState` passed to `run`, never on `self` (construction-time
    configuration like "which `LLMPort` to use" is fine on `self`; anything
    that varies *per run* is not). This is what lets the same `Agent`
    instance safely run multiple times, or concurrently, over different
    `RunState`s without one run's effects leaking into another's.
    """

    name: str

    def run(self, state: RunState) -> RunState:
        """Process `state` and return the next state."""
        ...


__all__ = ["Agent"]
