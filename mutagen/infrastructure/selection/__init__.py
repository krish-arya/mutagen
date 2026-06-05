"""Selection adapters implementing :class:`TargetSelector`.

The :class:`AstTargetSelector` composes three focused components:

* :class:`CoverageAnalyzer` — runs ``coverage.py`` and extracts line data;
* :class:`FunctionExtractor` — parses source into functions via ``ast``; and
* :class:`TargetRanker` — filters and ranks them into ordered targets.
"""

from mutagen.infrastructure.selection.ast_selector import AstTargetSelector
from mutagen.infrastructure.selection.call_graph_analyzer import AstCallGraphAnalyzer
from mutagen.infrastructure.selection.coverage_analyzer import (
    CoverageAnalyzer,
    FileCoverage,
    ProjectCoverage,
)
from mutagen.infrastructure.selection.function_extractor import (
    ExtractedFunction,
    ExtractionError,
    FunctionExtractor,
)
from mutagen.infrastructure.selection.target_ranker import (
    FilterReason,
    ScoredFunction,
    TargetRanker,
)

__all__ = [
    "AstTargetSelector",
    "AstCallGraphAnalyzer",
    "CoverageAnalyzer",
    "ProjectCoverage",
    "FileCoverage",
    "FunctionExtractor",
    "ExtractedFunction",
    "ExtractionError",
    "TargetRanker",
    "ScoredFunction",
    "FilterReason",
]
