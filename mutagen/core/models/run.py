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
class RunReport:
    """A summarized, report-ready view of a :class:`RunResult`.

    Where :class:`RunResult` holds the full detail, ``RunReport`` holds the
    headline numbers a :class:`mutagen.core.interfaces.Reporter` renders.

    Attributes:
        run_id: Identifier of the run being reported.
        status: Terminal status of the run.
        total_targets: Number of targets processed.
        covered_targets: Number of targets that reached COVERED status.
        total_tests_generated: Count of generated tests across the run.
        mutation_score: Overall mutation score in ``[0, 1]``.
        cost: Total run cost.
        notes: Optional, ordered human-readable annotations.
    """

    run_id: str
    status: RunStatus
    total_targets: int = 0
    covered_targets: int = 0
    total_tests_generated: int = 0
    mutation_score: float = 0.0
    cost: CostInfo = field(default_factory=CostInfo.zero)
    notes: tuple[str, ...] = field(default_factory=tuple)

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
                ``covered_targets`` exceeds ``total_targets``, the mutation
                score is outside ``[0, 1]``, or the cost is invalid.
        """
        if not self.run_id.strip():
            raise ValidationError("RunReport.run_id must be non-empty.")
        for name, value in (
            ("total_targets", self.total_targets),
            ("covered_targets", self.covered_targets),
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
        if not 0.0 <= self.mutation_score <= 1.0:
            raise ValidationError(
                "RunReport.mutation_score must be in [0.0, 1.0], got "
                f"{self.mutation_score}."
            )
        self.cost.validate()
