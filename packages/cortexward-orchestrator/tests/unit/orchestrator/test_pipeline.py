"""Unit tests for `build_pipeline`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import AgentOrchestrator
from cortexward.llm import LLMProviderConfig, Provider
from cortexward.orchestrator import SequentialOrchestrator, build_pipeline
from cortexward.ports import OrchestratorPort

pytestmark = pytest.mark.unit


class TestBuildPipeline:
    def test_no_llm_config_returns_a_sequential_orchestrator(self, tmp_path: Path) -> None:
        orchestrator = build_pipeline(llm_config=None, root=tmp_path)
        assert isinstance(orchestrator, SequentialOrchestrator)

    def test_an_llm_config_returns_an_agent_orchestrator(self, tmp_path: Path) -> None:
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(llm_config=config, root=tmp_path)
        assert isinstance(orchestrator, AgentOrchestrator)

    def test_result_always_satisfies_the_orchestrator_port(self, tmp_path: Path) -> None:
        assert isinstance(build_pipeline(llm_config=None, root=tmp_path), OrchestratorPort)
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        assert isinstance(build_pipeline(llm_config=config, root=tmp_path), OrchestratorPort)

    def test_no_reachability_still_builds_an_agent_orchestrator(self, tmp_path: Path) -> None:
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(llm_config=config, root=tmp_path, reachability=False)
        assert isinstance(orchestrator, AgentOrchestrator)

    def test_languages_are_accepted(self, tmp_path: Path) -> None:
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(
            llm_config=config, root=tmp_path, languages=("python",), reachability=True
        )
        assert isinstance(orchestrator, AgentOrchestrator)
