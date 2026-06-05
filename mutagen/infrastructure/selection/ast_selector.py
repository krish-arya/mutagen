"""Coverage-guided :class:`TargetSelector` adapter.

Composes the three selection components to implement the port:

* :class:`CoverageAnalyzer` measures which lines the test suite executes;
* :class:`FunctionExtractor` parses each source file into functions; and
* :class:`TargetRanker` filters and ranks them into ordered targets.

The result is a sequence of :class:`Target` objects ordered worst-covered
first, ready for the test-generation stage.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import MutagenError
from mutagen.core.interfaces import TargetSelector
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target
from mutagen.infrastructure.process import CommandRunner
from mutagen.infrastructure.selection.coverage_analyzer import (
    CoverageAnalyzer,
    ProjectCoverage,
)
from mutagen.infrastructure.selection.function_extractor import (
    ExtractionError,
    FunctionExtractor,
)
from mutagen.infrastructure.selection.target_ranker import TargetRanker

_logger = get_logger(__name__)


class AstTargetSelector(TargetSelector):
    """Selects targets by combining coverage analysis with AST extraction.

    Args:
        config: The run configuration.
        analyzer: Coverage analyzer; injected for tests. Defaults to a real
            :class:`CoverageAnalyzer`.
        extractor: Function extractor; injected for tests.
        ranker: Target ranker; injected for tests.
        runner: Subprocess runner shared with a default analyzer.
    """

    def __init__(
        self,
        config: RunConfig,
        *,
        analyzer: CoverageAnalyzer | None = None,
        extractor: FunctionExtractor | None = None,
        ranker: TargetRanker | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self._config = config
        self._analyzer = analyzer or CoverageAnalyzer(config, runner=runner)
        self._extractor = extractor or FunctionExtractor()
        self._ranker = ranker or TargetRanker(config.selection)

    async def select(self, context: RepoContext) -> Sequence[Target]:
        """Select and rank targets from ``context``.

        Runs coverage once for the whole project, then extracts and ranks each
        source file, merging the per-file targets into a single ordering.

        Args:
            context: The ingested repository snapshot.

        Returns:
            Targets ordered by descending priority (worst-covered first),
            capped by ``SelectionConfig.max_targets`` when set.
        """
        coverage = await self._safe_analyze(context)

        all_targets: list[Target] = []
        for rel_path in context.source_files:
            all_targets.extend(self._rank_file(context.root, rel_path, coverage))

        all_targets.sort(key=lambda t: (-t.priority, t.qualified_name))

        limit = self._config.selection.max_targets
        if limit > 0:
            all_targets = all_targets[:limit]

        _logger.info(
            "selection complete",
            extra={
                "context": {
                    "files": len(context.source_files),
                    "targets": len(all_targets),
                    "coverage_measured": not coverage.is_empty,
                }
            },
        )
        return all_targets

    async def _safe_analyze(self, context: RepoContext) -> ProjectCoverage:
        """Measure coverage, degrading to empty coverage on failure.

        A coverage failure should not abort selection: with no coverage data
        every function is treated as uncovered, which is a safe, conservative
        default (everything becomes a candidate).
        """
        try:
            return await self._analyzer.analyze(context.root)
        except MutagenError as exc:
            _logger.warning(
                "coverage analysis failed; treating all lines as uncovered",
                extra={"context": {"error": str(exc)}},
            )
            return ProjectCoverage()

    def _rank_file(
        self, root: Path, rel_path: Path, coverage: ProjectCoverage
    ) -> list[Target]:
        """Extract and rank a single source file, skipping unparsable files."""
        abs_path = root / rel_path
        try:
            functions = self._extractor.extract_file(abs_path)
        except ExtractionError as exc:
            _logger.warning(
                "skipping unparsable source file",
                extra={"context": {"file": str(rel_path), "error": str(exc)}},
            )
            return []
        return self._ranker.rank_file(rel_path, functions, coverage.for_file(rel_path))
