# cortexward-reporters

Standards-aligned output-format adapters for
[CortexWard](https://github.com/amarjaleelbanbhan/CortexWard), each implementing the
`ReporterPort` port to render the domain `Finding` model into an external format (SARIF today;
VEX/SBOM/Markdown are future work) without coupling the internal model to any one of them.

See [MPS §17.1](../../docs/specifications/MPS-v1.0.md) for the port contract.
