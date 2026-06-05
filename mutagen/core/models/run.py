"""Run-level domain models.

:class:`RunResult` is the raw, aggregated data produced by executing the
pipeline over every selected target. :class:`RunReport` is the summarized,
report-ready view derived from a :class:`RunResult`, suitable for rendering by
a :class:`mutagen.core.interfaces.Reporter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.outcome import OutcomeStatus, TargetOutcome


class RunStatus(str, Enum):
    """Terminal status of a completed run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RunResult:
    """The raw aggregated result of a full pipeline run.

    Attributes:
        run_id: Stable unique identifier for the run.
        status: Terminal status of the run.
        outcomes: Per-target outcomes for every target processed.
        cost: Total cost across the whole run.
        duration_seconds: End-to-end wall-clock duration of the run.
        started_at: Unix epoch seconds when the run began.
        finished_at: Unix epoch seconds when the run completed.
    """

    run_id: str
    status: RunStatus
    outcomes: tuple[TargetOutcome, ...] = field(default_factory=tuple)
    cost: CostInfo = field(default_factory=CostInfo.zero)
    duration_seconds: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def covered_targets(self) -> int:
        """Number of targets that reached COVERED status."""
        return sum(
            1 for o in self.outcomes if o.status is OutcomeStatus.COVERED
        )

    def validate(self) -> None:
        """Validate the run result and all nested outcomes.

        Raises:
            ValidationError: If the run id is blank, the timestamps are
                inconsistent, or any nested cost/outcome is invalid.
        """
        if not self.run_id.strip():
            raise ValidationError("RunResult.run_id must be non-empty.")
        if self.finished_at and self.finished_at < self.started_at:
            raise ValidationError(
                "RunResult.finished_at precedes started_at."
            )
        if self.duration_seconds < 0:
            raise ValidationError(
                "RunResult.duration_seconds must be non-negative."
            )
        self.cost.validate()
        for outcome in self.outcomes:
            outcome.validate()


@dataclass(frozen=True, slots=True)
class TargetStat:
    """Per-target headline numbers for the report.

    Attributes:
        target_id: Identifier of the target.
        qualified_name: Dotted name of the target symbol.
        status: The target's terminal outcome status.
        kept: Whether the target's generated tests were kept.
        tests_generated: Number of tests generated for the target.
        mutation_score: Post-generation mutation score in ``[0, 1]``.
        cost: Cost attributed to the target.
    """

    target_id: str
    qualified_name: str
    status: OutcomeStatus
    kept: bool
    tests_generated: int = 0
    mutation_score: float = 0.0
    cost: CostInfo = field(default_factory=CostInfo.zero)


@dataclass(frozen=True, slots=True)
class RunReport:
    """A summarized, report-ready view of a :class:`RunResult`.

    Where :class:`RunResult` holds the full detail, ``RunReport`` holds the
    headline numbers a :class:`mutagen.core.interfaces.Reporter` renders.

    Attributes:
        run_id: Identifier of the run being reported.
        status: Terminal status of the run.
        total_targets: Number of targets processed.
        covered_targets: Number of targets that reached COVERED status.
        kept_targets: Number of targets whose tests were kept.
        discarded_targets: Number of targets whose tests were discarded.
        total_tests_generated: Count of generated tests across the run.
        mutation_score: Overall (after) mutation score in ``[0, 1]``.
        mutation_score_before: Baseline mutation score using only the repo's
            pre-existing tests, or ``None`` when no baseline was measured.
        cost: Total run cost.
        duration_seconds: End-to-end wall-clock duration.
        target_stats: Per-target headline statistics.
        notes: Optional, ordered human-readable annotations.
    """

    run_id: str
    status: RunStatus
    total_targets: int = 0
    covered_targets: int = 0
    kept_targets: int = 0
    discarded_targets: int = 0
    total_tests_generated: int = 0
    mutation_score: float = 0.0
    mutation_score_before: float | None = None
    cost: CostInfo = field(default_factory=CostInfo.zero)
    duration_seconds: float = 0.0
    target_stats: tuple[TargetStat, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def mutation_score_after(self) -> float:
        """Alias for the achieved (post-generation) mutation score."""
        return self.mutation_score

    @property
    def score_delta(self) -> float | None:
        """Improvement in mutation score, or ``None`` without a baseline."""
        if self.mutation_score_before is None:
            return None
        return self.mutation_score - self.mutation_score_before

    @property
    def coverage_ratio(self) -> float:
        """Fraction of processed targets that were covered, in ``[0, 1]``."""
        if self.total_targets == 0:
            return 0.0
        return self.covered_targets / self.total_targets

    def validate(self) -> None:
        """Validate the report's invariants.

        Raises:
            ValidationError: If the run id is blank, counts are negative,
                ``covered_targets`` exceeds ``total_targets``, a mutation
                score is outside ``[0, 1]``, or the cost is invalid.
        """
        if not self.run_id.strip():
            raise ValidationError("RunReport.run_id must be non-empty.")
        for name, value in (
            ("total_targets", self.total_targets),
            ("covered_targets", self.covered_targets),
            ("kept_targets", self.kept_targets),
            ("discarded_targets", self.discarded_targets),
            ("total_tests_generated", self.total_tests_generated),
        ):
            if value < 0:
                raise ValidationError(
                    f"RunReport.{name} must be non-negative, got {value}."
                )
        if self.covered_targets > self.total_targets:
            raise ValidationError(
                "RunReport.covered_targets exceeds total_targets "
                f"({self.covered_targets} > {self.total_targets})."
            )
        for name, score in (
            ("mutation_score", self.mutation_score),
            ("mutation_score_before", self.mutation_score_before),
        ):
            if score is not None and not 0.0 <= score <= 1.0:
                raise ValidationError(
                    f"RunReport.{name} must be in [0.0, 1.0], got {score}."
                )
        if self.duration_seconds < 0:
            raise ValidationError(
                "RunReport.duration_seconds must be non-negative."
            )
        self.cost.validate()
