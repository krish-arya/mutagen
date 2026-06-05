"""Call-graph-analyzer port.

A :class:`CallGraphAnalyzer` reads a :class:`RepoContext` and builds a
:class:`CallGraph` — a repo-wide map from each function to the functions it
calls. The generation pipeline uses it to gather a target's whole execution
path (its transitive callees) rather than treating the target in isolation.

How the graph is built (``ast``, tree-sitter, or otherwise) is an
implementation concern; the port speaks only in domain models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mutagen.core.models.call_graph import CallGraph
from mutagen.core.models.repo import RepoContext


class CallGraphAnalyzer(ABC):
    """Port for building a repository-wide call graph."""

    @abstractmethod
    def analyze(self, context: RepoContext) -> CallGraph:
        """Build a :class:`CallGraph` for the ingested repository.

        Args:
            context: The ingested repository snapshot to analyse.

        Returns:
            A :class:`CallGraph` over the repo's source files. Unparsable files
            are skipped rather than aborting the whole analysis; the result may
            be empty if nothing could be analysed.
        """
        raise NotImplementedError
