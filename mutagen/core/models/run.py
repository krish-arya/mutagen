"""Run-level domain models.

These aggregate the results of an entire mutation-testing run into a summary
suitable for reporting and threshold checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mutagen.core.models.mutant import MutantResult, MutantStatus


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Headline statistics for a completed run."""

    total: int = 0
    killed: int = 0
    survived: int = 0
    timed_out: int = 0
    errored: int = 0
    skipped: int = 0

    @property
    def evaluated(self) -> int:
        """Number of mutants that produced a definitive verdict."""
        return self.killed + self.survived + self.timed_out

    @property
    def mutation_score(self) -> float:
        """Fraction of evaluated mutants that were killed, in ``[0, 1]``.

        Timeouts are counted as kills, matching common convention.
        """
        if self.evaluated == 0:
            return 0.0
        return (self.killed + self.timed_out) / self.evaluated


@dataclass(frozen=True, slots=True)
class RunResult:
    """The complete result of a mutation-testing run.

    Attributes:
        results: Per-mutant evaluation results.
        summary: Aggregate statistics derived from ``results``.
    """

    results: tuple[MutantResult, ...] = field(default_factory=tuple)
    summary: RunSummary = field(default_factory=RunSummary)

    @property
    def survivors(self) -> tuple[MutantResult, ...]:
        """Results for mutants that escaped detection."""
        return tuple(
            r for r in self.results if r.status is MutantStatus.SURVIVED
        )
