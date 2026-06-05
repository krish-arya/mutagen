"""Filtering and ranking of extracted functions into ordered targets.

:class:`TargetRanker` is the policy engine of selection. Given the functions
extracted from a file and the project's coverage data, it:

1. computes each function's coverage fraction (executed body lines / body
   lines);
2. filters out functions that are not worth generating tests for (trivial,
   giant, or property getters);
3. scores the survivors with a weighted blend of under-coverage and size; and
4. emits :class:`Target` objects ordered by descending priority (lowest
   coverage / largest first).

It is pure: no filesystem or subprocess access. Coverage and extraction are
provided by collaborators, keeping ranking independently testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import SelectionConfig
from mutagen.core.models.location import SourceSpan
from mutagen.core.models.target import Target
from mutagen.infrastructure.selection.coverage_analyzer import FileCoverage
from mutagen.infrastructure.selection.function_extractor import ExtractedFunction

_logger = get_logger(__name__)


class FilterReason(str, Enum):
    """Why a function was excluded from selection."""

    TRIVIAL = "trivial"
    GIANT = "giant"
    PROPERTY_GETTER = "property_getter"


@dataclass(frozen=True, slots=True)
class ScoredFunction:
    """An extracted function annotated with its coverage and score.

    Attributes:
        function: The underlying extracted function.
        coverage: Fraction of body lines executed, in ``[0, 1]``. ``1.0`` when
            the function has no measurable body lines.
        priority: The computed selection priority in ``[0, 1]``.
    """

    function: ExtractedFunction
    coverage: float
    priority: float


class TargetRanker:
    """Filters and ranks extracted functions into ordered targets."""

    def __init__(self, config: SelectionConfig) -> None:
        self._config = config

    def rank_file(
        self,
        rel_path: Path,
        functions: list[ExtractedFunction],
        coverage: FileCoverage | None,
    ) -> list[Target]:
        """Rank a single file's functions into ordered targets.

        Args:
            rel_path: Repo-relative path of the source file.
            functions: Functions extracted from the file.
            coverage: Coverage for the file, or ``None`` if unmeasured (treated
                as fully uncovered).

        Returns:
            Targets for the file's selected functions, ordered by descending
            priority.
        """
        scored: list[ScoredFunction] = []
        for func in functions:
            reason = self._filter_reason(func)
            if reason is not None:
                _logger.debug(
                    "function filtered",
                    extra={
                        "context": {
                            "function": func.qualified_name,
                            "file": str(rel_path),
                            "reason": reason.value,
                        }
                    },
                )
                continue
            cov = self.coverage_fraction(func, coverage)
            priority = self._priority(func, cov)
            scored.append(ScoredFunction(func, cov, priority))

        scored.sort(key=self._sort_key)
        return [self._to_target(rel_path, s) for s in scored]

    # ------------------------------------------------------------------ #
    # Coverage
    # ------------------------------------------------------------------ #

    @staticmethod
    def coverage_fraction(
        func: ExtractedFunction, coverage: FileCoverage | None
    ) -> float:
        """Compute the executed fraction of a function's body lines.

        A function with no measurable body lines (e.g. only a docstring or
        ``pass``) is treated as fully covered so it never floats to the top.

        Args:
            func: The function to measure.
            coverage: Coverage for the enclosing file, or ``None``.

        Returns:
            Coverage fraction in ``[0, 1]``.
        """
        body = func.body_lines
        if not body:
            return 1.0
        if coverage is None:
            return 0.0
        executed = len(body & coverage.executed_lines)
        return executed / len(body)

    # ------------------------------------------------------------------ #
    # Filtering
    # ------------------------------------------------------------------ #

    def _filter_reason(self, func: ExtractedFunction) -> FilterReason | None:
        """Return why ``func`` should be excluded, or ``None`` to keep it."""
        cfg = self._config
        if cfg.exclude_property_getters and func.is_property:
            return FilterReason.PROPERTY_GETTER
        if func.statement_count <= cfg.trivial_max_statements:
            return FilterReason.TRIVIAL
        if func.statement_count > cfg.giant_max_statements:
            return FilterReason.GIANT
        return None

    # ------------------------------------------------------------------ #
    # Scoring & ordering
    # ------------------------------------------------------------------ #

    def _priority(self, func: ExtractedFunction, coverage: float) -> float:
        """Blend under-coverage and normalized size into a [0,1] priority."""
        cfg = self._config
        under_coverage = 1.0 - coverage
        size_norm = self._normalized_size(func)
        weight_sum = cfg.coverage_weight + cfg.size_weight
        if weight_sum <= 0:
            return under_coverage
        raw = cfg.coverage_weight * under_coverage + cfg.size_weight * size_norm
        return max(0.0, min(1.0, raw / weight_sum))

    def _normalized_size(self, func: ExtractedFunction) -> float:
        """Map statement count to ``[0, 1]`` against the giant threshold."""
        ceiling = max(1, self._config.giant_max_statements)
        return min(1.0, func.statement_count / ceiling)

    @staticmethod
    def _sort_key(scored: ScoredFunction) -> tuple[float, float, str]:
        """Order by descending priority, then ascending coverage, then name.

        The name tiebreaker keeps ordering deterministic across runs.
        """
        return (
            -scored.priority,
            scored.coverage,
            scored.function.qualified_name,
        )

    # ------------------------------------------------------------------ #
    # Target construction
    # ------------------------------------------------------------------ #

    def _to_target(self, rel_path: Path, scored: ScoredFunction) -> Target:
        """Build a validated :class:`Target` from a scored function."""
        func = scored.function
        qualified_name = self._qualified_name(rel_path, func.qualified_name)
        target = Target(
            target_id=self._target_id(rel_path, func),
            qualified_name=qualified_name,
            kind=func.kind,
            span=SourceSpan(
                path=rel_path,
                start_line=func.start_line,
                end_line=func.end_line,
            ),
            priority=scored.priority,
            signature=f"{func.qualified_name} ({scored.coverage:.0%} covered)",
        )
        target.validate()
        return target

    @staticmethod
    def _qualified_name(rel_path: Path, func_qualname: str) -> str:
        """Combine the module dotted path with the function's qualname."""
        module = ".".join(rel_path.with_suffix("").parts)
        return f"{module}.{func_qualname}" if module else func_qualname

    @staticmethod
    def _target_id(rel_path: Path, func: ExtractedFunction) -> str:
        """Derive a stable id from the file, name, and start line."""
        digest = hashlib.sha1(
            f"{rel_path}::{func.qualified_name}::{func.start_line}".encode()
        ).hexdigest()
        return digest[:16]
