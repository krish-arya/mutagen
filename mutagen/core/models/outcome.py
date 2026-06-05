"""Per-target outcome and mutation-result domain models.

A :class:`MutationResult` records what happened to one mutant when the
generated tests ran against it; a :class:`TargetOutcome` aggregates the verdict
for a single :class:`Target` across all its generated tests and mutants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.cost import CostInfo


class MutationVerdict(str, Enum):
    """Whether the generated tests detected a given mutant."""

    KILLED = "killed"
    SURVIVED = "survived"
    TIMEOUT = "timeout"
    ERROR = "error"


class OutcomeStatus(str, Enum):
    """The overall verdict for a target after generation and validation."""

    COVERED = "covered"
    UNCOVERED = "uncovered"
    GENERATION_FAILED = "generation_failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class MutationResult:
    """The result of running the generated tests against one mutant.

    Attributes:
        mutant_id: Identifier of the mutant that was evaluated.
        verdict: Whether the mutant was killed, survived, etc.
        killing_test_ids: Ids of generated tests that detected the mutant.
        duration_seconds: Wall-clock time to evaluate the mutant.
        detail: Optional diagnostic detail (e.g. error/timeout text).
    """

    mutant_id: str
    verdict: MutationVerdict
    killing_test_ids: tuple[str, ...] = field(default_factory=tuple)
    duration_seconds: float = 0.0
    detail: str = ""

    @property
    def is_killed(self) -> bool:
        """Whether the mutant was detected by at least one generated test."""
        return self.verdict is MutationVerdict.KILLED

    def validate(self) -> None:
        """Validate the mutation result's invariants.

        Raises:
            ValidationError: If the mutant id is blank, the duration is
                negative, or the verdict is KILLED without any killing test.
        """
        if not self.mutant_id.strip():
            raise ValidationError("MutationResult.mutant_id must be non-empty.")
        if self.duration_seconds < 0:
            raise ValidationError(
                "MutationResult.duration_seconds must be non-negative."
            )
        if self.verdict is MutationVerdict.KILLED and not self.killing_test_ids:
            raise ValidationError(
                "MutationResult with verdict KILLED must name a killing test."
            )


@dataclass(frozen=True, slots=True)
class TargetOutcome:
    """Aggregate verdict for a single target after the pipeline runs.

    Attributes:
        target_id: Identifier of the target this outcome describes.
        status: Overall verdict for the target.
        generated_test_ids: Ids of the tests synthesized for the target.
        mutation_results: Per-mutant results for mutants on this target.
        cost: Total cost attributed to processing this target.
        detail: Optional diagnostic detail (e.g. failure reason).
    """

    target_id: str
    status: OutcomeStatus
    generated_test_ids: tuple[str, ...] = field(default_factory=tuple)
    mutation_results: tuple[MutationResult, ...] = field(default_factory=tuple)
    cost: CostInfo = field(default_factory=CostInfo.zero)
    detail: str = ""

    @property
    def killed_count(self) -> int:
        """Number of mutants on this target that were killed."""
        return sum(1 for r in self.mutation_results if r.is_killed)

    @property
    def mutation_score(self) -> float:
        """Fraction of this target's mutants that were killed, in ``[0, 1]``."""
        if not self.mutation_results:
            return 0.0
        return self.killed_count / len(self.mutation_results)

    def validate(self) -> None:
        """Validate the outcome and all nested mutation results.

        Raises:
            ValidationError: If the target id is blank, or any nested cost or
                mutation result is invalid.
        """
        if not self.target_id.strip():
            raise ValidationError("TargetOutcome.target_id must be non-empty.")
        self.cost.validate()
        for result in self.mutation_results:
            result.validate()
