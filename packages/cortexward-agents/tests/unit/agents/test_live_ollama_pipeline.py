"""End-to-end `AgentOrchestrator` run against a real local Ollama server.

Genuinely exercises Planner -> Scanner -> Verifier -> Repair -> Reviewer ->
Memory -> Coordinator over a real `BanditScanner` finding, a real
`build_code_graphs`-produced `CodeGraph`, and real `qwen2.5-coder:7b`
completions -- not mocked, matching the `TestLiveOllama` pattern already
established in `cortexward-llm`'s `test_ollama_adapter.py`. Skipped when no
local Ollama server is reachable (this project's CI has none installed).
Kept to exactly one fixture vulnerability, so exactly one Verifier call is
made -- each real Ollama call takes 30+ seconds, and this pipeline also
makes a Planner and a Coordinator call regardless of finding count.

The vulnerable call is a direct statement inside an
``if __name__ == "__main__":`` guard rather than in a separately-defined
function: the reference CFG builder currently only links CFG_NEXT edges
between sibling statements at the same nesting level, not from a function
definition into its own body (verified empirically against the real
`PythonLanguageProvider` while building this test, not assumed) -- so a
call wrapped in a helper function isn't yet reachability-provable, while a
direct statement in the entrypoint-marked guard is.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from urllib.error import URLError

import pytest

from cortexward.agents import AgentOrchestrator, build_code_graphs, default_agents
from cortexward.domain import EvidenceKind, FindingState
from cortexward.llm import OllamaAdapter
from cortexward.ports import AnalysisRequest
from cortexward.scanners import BanditScanner

_LIVE_OLLAMA_URL = "http://localhost:11434"
_LIVE_MODEL = "qwen2.5-coder:7b"

_VULNERABLE_SOURCE = """\
import subprocess

if __name__ == "__main__":
    subprocess.call("echo hi", shell=True)
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
        code_graphs = build_code_graphs(tmp_path, languages=("python",))
        agents = default_agents(llm=llm, scanners=(BanditScanner(),), code_graphs=code_graphs)
        orchestrator = AgentOrchestrator(agents)

        result = orchestrator.run(AnalysisRequest(root=tmp_path, languages=("python",)))

        assert result.run_id.startswith("run_")
        assert len(result.findings) >= 1
        # Bandit also flags the bare `import subprocess` (B404) at line 1,
        # which the entrypoint guard doesn't reach -- find the finding at
        # the actual vulnerable call (line 4) rather than assuming order.
        finding = next(
            f for f in result.findings if any(loc.start_line == 4 for loc in f.locations)
        )
        assert finding.rule_id
        # Reachability is deterministic (no LLM involved): the entrypoint
        # guard directly contains the flagged call, so real graph analysis
        # must have proven it and attached genuine independent evidence.
        assert any(e.kind == EvidenceKind.REACHABILITY_PROOF for e in finding.evidence)
        # The Verifier also genuinely called the model: an LLM_ASSESSMENT
        # evidence item was attached (REAL or FALSE_POSITIVE), or the
        # model's response didn't parse as one of the three verdicts and no
        # LLM evidence was added -- both are legitimate outcomes of a real
        # model call, so only the resulting state is constrained here.
        assert finding.state in (
            FindingState.CANDIDATE,
            FindingState.TRIAGED,
            FindingState.REFUTED,
        )
