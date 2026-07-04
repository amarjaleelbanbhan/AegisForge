# aegisforge-core

The pure domain core of [AegisForge](https://github.com/amarjaleelbanbhan/AegisForge): findings,
evidence, the Verification Ladder, port contracts, and the plugin registry.

This package has no I/O and depends on nothing beyond `pydantic`. Every AegisForge installation
requires it; adapters (scanners, LLM providers, sandboxes, ...) depend on it, never the reverse.
See the [Master Project Specification](../../docs/specifications/MPS-v1.0.md) for the full
architecture.
