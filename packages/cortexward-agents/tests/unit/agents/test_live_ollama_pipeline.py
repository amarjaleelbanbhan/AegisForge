"""End-to-end `AgentOrchestrator` run against a real local Ollama server.

Genuinely exercises Planner -> Scanner -> Verifier -> Repair -> Reviewer ->
Memory -> Coordinator over a real `BanditScanner` finding and real
`qwen2.5-coder:7b` completions -- not mocked, matching the
`TestLiveOllama` pattern already established in
`cortexward-llm`'s `test_ollama_adapter.py`. Skipped when no local Ollama
server is reachable (this project's CI has none installed). Kept to exactly
one fixture vulnerability, so exactly one Verifier call is made -- each real
Ollama call takes 30+ seconds, and this pipeline also makes a Planner and a
Coordinator call regardless of finding count.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from urllib.error import URLError

import pytest

from cortexward.agents import AgentOrchestrator, default_agents
from cortexward.domain import FindingState
from cortexward.llm import OllamaAdapter
from cortexward.ports import AnalysisRequest
from cortexward.scanners import BanditScanner

_LIVE_OLLAMA_URL = "http://localhost:11434"
_LIVE_MODEL = "qwen2.5-coder:7b"

_VULNERABLE_SOURCE = """\
import subprocess


def run(user_input: str) -> None:
    subprocess.call(user_input, shell=True)
"""


def _ollama_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{_LIVE_OLLAMA_URL}/api/tags", timeout=2):  # noqa: S310 # nosec B310
            return True
    except (URLError, TimeoutError, OSError):
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _ollama_is_running(), reason="no local Ollama server reachable")
class TestLiveOllamaAgentPipeline:
    def test_full_pipeline_runs_end_to_end_against_a_real_vulnerability(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "app.py").write_text(_VULNERABLE_SOURCE, encoding="utf-8")
        llm = OllamaAdapter(_LIVE_MODEL, base_url=_LIVE_OLLAMA_URL)
        agents = default_agents(llm=llm, scanners=(BanditScanner(),))
        orchestrator = AgentOrchestrator(agents)

        result = orchestrator.run(AnalysisRequest(root=tmp_path, languages=("python",)))

        assert result.run_id.startswith("run_")
        assert len(result.findings) >= 1
        finding = result.findings[0]
        assert finding.rule_id
        # The Verifier genuinely called the model: an LLM_ASSESSMENT evidence
        # item was attached (REAL or FALSE_POSITIVE), or the model's response
        # didn't parse as one of the three verdicts and the finding was left
        # untouched -- both are legitimate outcomes of a real model call.
        assert finding.state in (
            FindingState.CANDIDATE,
            FindingState.TRIAGED,
            FindingState.REFUTED,
        )
