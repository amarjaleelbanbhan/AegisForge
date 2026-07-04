# ADR-0006: Own the LLM abstraction; providers are adapters

**Status:** Accepted · **Date:** 2026-07-05

## Context
AegisForge must support Anthropic, OpenAI, Gemini, Ollama, vLLM, and LiteLLM-compatible providers,
with a local/offline mode. Depending on one vendor SDK, or on LiteLLM *as the abstraction*, trades
many lock-ins for one and couples us to that library's model.

## Decision
Define an **owned `LLMPort` protocol** (structured output, tool-calling, streaming, token
accounting, cost) in `aegisforge-llm`. Ship native **Anthropic** and **OpenAI** adapters, a
**Gemini** adapter, an **Ollama** adapter, an **OpenAI-compatible** adapter (covers vLLM and most
gateways), and a **LiteLLM** adapter as a catch-all backend. Add a config-driven, cost-aware
**model router** (task class → model tier). No provider type leaks past the port; every capability
works with interchangeable models; local/offline pins to local models.

## Consequences
- No single-vendor dependency; researchers can swap models freely and record versions.
- We maintain a thin protocol + a handful of adapters.
- Provider-specific features are exposed only through capability flags, not leaked types.

## Alternatives considered
- **LiteLLM as the core abstraction.** Rejected: lock-in to its interface and release cadence;
  kept instead as one interchangeable adapter.
- **Single-provider SDK.** Rejected: violates the no-single-provider requirement.

*Specified in [MPS §14](../specifications/MPS-v1.0.md#14-llm-abstraction--model-routing).*
