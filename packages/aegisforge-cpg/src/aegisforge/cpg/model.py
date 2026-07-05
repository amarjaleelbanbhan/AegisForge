"""The Code Property Graph's node/edge schema (MPS §12).

A CPG unifies four kinds of edges over one set of nodes: AST structure,
control flow, data flow, and calls. The schema here is intentionally
language-agnostic — a :class:`~aegisforge.ports.language_provider.
LanguageProvider` maps its language's constructs onto these node/edge kinds
when it builds a graph with :class:`~aegisforge.cpg.graph.GraphBuilder`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from aegisforge.domain import SourceLocation
from aegisforge.ports import NodeId


class NodeKind(StrEnum):
    """The syntactic/semantic role of one CPG node."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    PARAMETER = "parameter"
    CALL = "call"
    ASSIGNMENT = "assignment"
    LITERAL = "literal"
    IDENTIFIER = "identifier"
    BRANCH = "branch"
    RETURN = "return"
    IMPORT = "import"
    OTHER = "other"
    """A parsed construct with no dedicated kind yet; refined over time."""


class EdgeKind(StrEnum):
    """The relationship one CPG edge represents."""

    AST_CHILD = "ast_child"
    """Syntactic containment: parent -> child in the parse tree."""

    CFG_NEXT = "cfg_next"
    """Control may proceed from source to target."""

    DFG_REACHES = "dfg_reaches"
    """A value defined at source may reach (be used at) target."""

    CALLS = "calls"
    """source invokes the function identified by target."""

    IMPORTS = "imports"
    """source's module depends on target's module."""


class Node(BaseModel):
    """One CPG node: a syntactic or semantic construct at a source location."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: NodeId
    kind: NodeKind
    language: str
    location: SourceLocation
    properties: dict[str, str] = Field(default_factory=dict)
    """Free-form attributes, e.g. {"name": "handle_request"} for a FUNCTION node."""


class Edge(BaseModel):
    """One directed CPG edge between two node ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EdgeKind
    source: NodeId
    target: NodeId
