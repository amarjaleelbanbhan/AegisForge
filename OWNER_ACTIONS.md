# Owner Actions

Genuine human/infrastructure actions the autonomous agent cannot perform itself.
Everything else is already implemented, tested, and CI-green.

## 1. Observe the full exploit-verification loop live (Milestone 0)

**Why:** the combined loop needs one host with **both** a running Docker daemon
*and* a local Ollama server. CI has Docker but no Ollama; the dev box has Ollama
but its Docker Desktop engine would not finish starting. Starting/repairing a
local Docker engine (or adding Ollama to a Docker-capable host) is a host-level
action outside the codebase.

**Steps:**
1. On a machine with Docker installed, start the daemon and confirm: `docker info`.
2. Install and start Ollama, then pull the model:
   `ollama serve &` and `ollama pull qwen2.5-coder:7b`.
3. From the repo: `uv sync --all-packages --extra dev`.
4. Run the end-to-end loop test:
   `uv run pytest packages/cortexward-cli/tests/unit/cli/test_main.py -k TestLiveFullLoop -q`

**Expected result:** the test runs (not skipped) and passes — `ward scan
--llm-provider ollama --sandbox` on a command-injection fixture generates a PoC,
executes it in the Docker sandbox, and the finding reaches the `DYNAMIC_POC`
rung and `VERIFIED` state with genuine `EXPLOIT_POC` evidence.

**After completion:** nothing further is required in code — the loop is already
implemented, integrated, and 100 %-covered deterministically. This step only
turns the one remaining ⏳ verification level (full Ollama + Docker end-to-end)
into ✅. To also exercise it automatically in CI, add an Ollama service step to
`.github/workflows/ci.yml` (optional; the model pull adds several minutes).
