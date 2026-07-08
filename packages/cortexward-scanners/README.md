# cortexward-scanners

SAST/secret/dependency scanner adapters for
[CortexWard](https://github.com/amarjaleelbanbhan/CortexWard), each implementing the
`ScannerPort` port and yielding `RawFinding` records — normalization into the domain
`Finding` schema (cross-tool dedup/correlation) is a later Phase 3 step.

See [MPS §17.1](../../docs/specifications/MPS-v1.0.md) for the port contract.
