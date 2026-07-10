"""Unit tests for the `Agent` protocol."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import Agent, RunState
from cortexward.ports import AnalysisRequest

pytestmark = pytest.mark.unit


class _NoOpAgent:
    name = "noop"

    def run(self, state: RunState) -> RunState:
        return state.with_completed(self.name)


class _NotAnAgent:
    """Missing `run` — should not satisfy the protocol."""

    name = "broken"


class TestAgentProtocol:
    def test_a_conforming_class_satisfies_the_protocol(self) -> None:
        assert isinstance(_NoOpAgent(), Agent)

    def test_a_class_missing_run_does_not_satisfy_the_protocol(self) -> None:
        assert not isinstance(_NotAnAgent(), Agent)

    def test_run_returns_a_new_state(self, tmp_path: Path) -> None:
        state = RunState(request=AnalysisRequest(root=tmp_path))
        result = _NoOpAgent().run(state)
        assert result.completed_agents == ("noop",)
        assert state.completed_agents == ()
