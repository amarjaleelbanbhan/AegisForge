"""CortexWard port catalog (MPS §17.1).

A port is a :class:`typing.Protocol` boundary; concrete implementations are
adapters, discovered at runtime through the plugin registry
(:mod:`cortexward.plugins.registry`) rather than imported directly. This
package depends only on :mod:`cortexward.domain` and defines no adapters —
enforced by the "Ports declare contracts only" import-linter contract.
"""

from __future__ import annotations

from cortexward.ports.code_graph import CodeGraph, NodeId, TaintPath
from cortexward.ports.language_provider import LanguageProvider
from cortexward.ports.llm import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    EmbeddingPort,
    EmbeddingResult,
    LLMPort,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from cortexward.ports.orchestrator import AnalysisRequest, OrchestratorPort, RunResult
from cortexward.ports.reporter import RenderedArtifact, ReporterPort
from cortexward.ports.sandbox import (
    EgressPolicy,
    ExecutionResult,
    ExecutionSpec,
    ResourceLimits,
    SandboxPort,
)
from cortexward.ports.scanner import RawFinding, ScannerPort
from cortexward.ports.storage import (
    FindingEvent,
    FindingEventKind,
    StoragePort,
    materialize_finding,
)
from cortexward.ports.telemetry import SpanHandle, TelemetryPort
from cortexward.ports.vcs import PullRequestRef, VCSPort

__all__ = [
    "AnalysisRequest",
    "ChatMessage",
    "ChatRole",
    "CodeGraph",
    "CompletionRequest",
    "CompletionResult",
    "EgressPolicy",
    "EmbeddingPort",
    "EmbeddingResult",
    "ExecutionResult",
    "ExecutionSpec",
    "FindingEvent",
    "FindingEventKind",
    "LLMPort",
    "LanguageProvider",
    "NodeId",
    "OrchestratorPort",
    "PullRequestRef",
    "RawFinding",
    "RenderedArtifact",
    "ReporterPort",
    "ResourceLimits",
    "RunResult",
    "SandboxPort",
    "ScannerPort",
    "SpanHandle",
    "StoragePort",
    "TaintPath",
    "TelemetryPort",
    "TokenUsage",
    "ToolCall",
    "ToolSpec",
    "VCSPort",
    "materialize_finding",
]
