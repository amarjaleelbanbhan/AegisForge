# cortexward-llm

The owned LLM abstraction for [CortexWard](https://github.com/amarjaleelbanbhan/CortexWard)
(MPS §14, ADR-0006): `LLMPort` adapters and the cost-aware model router. No capability outside
this package depends on a specific provider SDK type — adapters are interchangeable behind
`LLMPort`.

Ships `OllamaAdapter` (a local, credential-free backend — Ollama runs entirely on-device) and
`ModelRouter` (declarative `TaskClass` → `ModelTier` → adapter routing, config-driven and
overridable per run, with an `offline` mode that pins every task to the local tier). Native
Anthropic/OpenAI/Gemini/OpenAI-compatible/LiteLLM adapters are future work.
