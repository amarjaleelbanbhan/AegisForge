"""Unit tests for `build_pipeline`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import AgentOrchestrator
from cortexward.llm import LLMProviderConfig, Provider
from cortexward.orchestrator import LangGraphOrchestrator, SequentialOrchestrator, build_pipeline
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

    def test_default_engine_is_agent_orchestrator(self, tmp_path: Path) -> None:
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(llm_config=config, root=tmp_path)
        assert isinstance(orchestrator, AgentOrchestrator)

    def test_langgraph_engine_returns_a_langgraph_orchestrator(self, tmp_path: Path) -> None:
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(llm_config=config, root=tmp_path, engine="langgraph")
        assert isinstance(orchestrator, LangGraphOrchestrator)

    def test_engine_is_ignored_without_an_llm_config(self, tmp_path: Path) -> None:
        orchestrator = build_pipeline(llm_config=None, root=tmp_path, engine="langgraph")
        assert isinstance(orchestrator, SequentialOrchestrator)

    def test_sandbox_true_inserts_the_poc_agent(self, tmp_path: Path) -> None:
        # Constructing the sandbox adapter needs no running Docker daemon
        # (the daemon is only touched when a PoC actually executes), so this
        # is a plain deterministic check that the wiring is present.
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(llm_config=config, root=tmp_path, sandbox=True)
        assert isinstance(orchestrator, AgentOrchestrator)
        assert "poc" in [agent.name for agent in orchestrator._agents]

    def test_sandbox_false_omits_the_poc_agent(self, tmp_path: Path) -> None:
        config = LLMProviderConfig(provider=Provider.OLLAMA, model="qwen2.5-coder:7b")
        orchestrator = build_pipeline(llm_config=config, root=tmp_path, sandbox=False)
        assert isinstance(orchestrator, AgentOrchestrator)
        assert "poc" not in [agent.name for agent in orchestrator._agents]

    def test_sandbox_is_ignored_without_an_llm_config(self, tmp_path: Path) -> None:
        orchestrator = build_pipeline(llm_config=None, root=tmp_path, sandbox=True)
        assert isinstance(orchestrator, SequentialOrchestrator)
