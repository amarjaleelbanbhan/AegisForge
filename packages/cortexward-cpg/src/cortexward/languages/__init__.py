"""Language-specific :class:`~cortexward.ports.LanguageProvider` implementations.

Each subpackage (``cortexward.languages.python``, ...) parses one language
into the CPG schema (:mod:`cortexward.cpg.model`) via
:class:`~cortexward.cpg.graph.GraphBuilder`. Python is the reference
implementation; other languages follow the same shape (MPS §6.1, §12).
"""

from __future__ import annotations
