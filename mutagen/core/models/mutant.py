"""Mutant domain models.

A :class:`Mutation` is the abstract description of a transformation; a
:class:`Mutant` is a concrete instance applied to a target; a
:class:`MutantResult` records the outcome after running the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mutagen.core.models.target import MutationTarget


class MutantStatus(str, Enum):
    """Terminal status of a mutant after evaluation."""

    KILLED = "killed"
    SURVIVED = "survived"
    TIMEOUT = "timeout"
    ERROR = "error"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class Mutation:
    """An abstract, operator-defined code transformation.

    Attributes:
        operator: Name of the operator that produced this mutation.
        original: The original source text being replaced.
        replacement: The mutated source text.
        description: Human-readable summary of the change.
    """

    operator: str
    original: str
    replacement: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class Mutant:
    """A concrete mutation applied to a specific target.

    Attributes:
        mutant_id: Stable unique identifier for this mutant.
        target: The location the mutation was applied to.
        mutation: The transformation that was applied.
    """

    mutant_id: str
    target: MutationTarget
    mutation: Mutation


@dataclass(frozen=True, slots=True)
class MutantResult:
    """The evaluation outcome for a single mutant.

    Attributes:
        mutant: The mutant that was evaluated.
        status: Terminal status of the evaluation.
        duration_seconds: Wall-clock time taken to evaluate.
        killing_tests: Identifiers of tests that detected the mutant.
        detail: Optional diagnostic detail (e.g. error text).
    """

    mutant: Mutant
    status: MutantStatus
    duration_seconds: float = 0.0
    killing_tests: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""

    @property
    def is_killed(self) -> bool:
        """Whether the mutant was detected by the test suite."""
        return self.status is MutantStatus.KILLED
