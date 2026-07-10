# cortexward-agents

The agent framework for [CortexWard](https://github.com/amarjaleelbanbhan/CortexWard) (MPS §13-§15):
`RunState`, the `Agent` protocol, the seven agents (Planner, Scanner, Verifier, Repair, Reviewer,
Coordinator, Memory), memory abstractions, versioned prompt templates, and LLM-resilience
(`ResilientLLM` retry/fallback) and tool-invocation primitives.

Agents are stateless functions over a shared, typed `RunState`: `Agent.run(state) -> state`.
Reasoning agents (Verifier, Repair, Reviewer, Planner) use an `LLMPort` — the reference
integration test suite runs them against a local Ollama server (`cortexward-llm`'s
`OllamaAdapter`), since that's the one backend buildable without provider credentials.
