# cortexward-core

The pure domain core of [CortexWard](https://github.com/amarjaleelbanbhan/CortexWard): findings,
evidence, the Verification Ladder, port contracts, and the plugin registry.

This package has no I/O and depends on nothing beyond `pydantic`. Every CortexWard installation
requires it; adapters (scanners, LLM providers, sandboxes, ...) depend on it, never the reverse.
See the [Master Project Specification](../../docs/specifications/MPS-v1.0.md) for the full
architecture.
