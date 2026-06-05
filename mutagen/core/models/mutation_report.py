"""Mutation-gate report model.

A :class:`MutationReport` is what the :class:`mutagen.core.interfaces.MutationGate`
produces for one target: the per-mutant results, the derived mutation score,
the keep/reject decision against the threshold, the surviving mutants, and a
feedback string suitable for steering a re-generation attempt.

It is distinct from :class:`mutagen.core.models.outcome.TargetOutcome` (the
pipeline-level aggregate): the report is the gate's own verdict object, richer
in survivor detail and carrying the decision and feedback the gate computes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.outcome import MutationResult, MutationVerdict


@dataclass(frozen=True, slots=True)
class MutationReport:
    """The gate's verdict for a target's generated tests.

    Attributes:
        target_id: Identifier of the target that was evaluated.
        results: Per-mutant results across every mutant that was run.
        threshold: Minimum mutation score required to keep the tests, in
            ``[0, 1]``.
        kept: The decision — whether the tests met the threshold and should be
            kept. ``True`` iff :attr:`mutation_score` >= :attr:`threshold`.
        survivor_feedback: Human-readable guidance derived from the surviving
            mutants, suitable as feedback for a re-generation attempt. Empty
            when nothing survived.
        detail: Optional diagnostic detail (e.g. why the run errored).
    """

    target_id: str
    results: tuple[MutationResult, ...] = field(default_factory=tuple)
    threshold: float = 0.0
    kept: bool = False
    survivor_feedback: str = ""
    detail: str = ""

    @property
    def total(self) -> int:
        """Number of mutants evaluated."""
        return len(self.results)

    @property
    def killed_count(self) -> int:
        """Number of mutants the tests detected."""
        return sum(1 for r in self.results if r.is_killed)

    @property
    def survivors(self) -> tuple[MutationResult, ...]:
        """Results for mutants that escaped detection."""
        return tuple(r for r in self.results if r.verdict is MutationVerdict.SURVIVED)

    @property
    def mutation_score(self) -> float:
        """Fraction of evaluated mutants that were killed, in ``[0, 1]``.

        Computed over mutants that produced a definitive verdict (killed or
        survived); timeouts and harness errors are excluded from the
        denominator so an infrastructure hiccup does not deflate the score.
        Returns ``0.0`` when there is nothing to score.
        """
        scored = [
            r
            for r in self.results
            if r.verdict in (MutationVerdict.KILLED, MutationVerdict.SURVIVED)
        ]
        if not scored:
            return 0.0
        killed = sum(1 for r in scored if r.is_killed)
        return killed / len(scored)

    def validate(self) -> None:
        """Validate the report and all nested results.

        Raises:
            ValidationError: If the target id is blank, the threshold is out of
                range, the ``kept`` flag is inconsistent with the score, or any
                nested mutation result is invalid.
        """
        if not self.target_id.strip():
            raise ValidationError("MutationReport.target_id must be non-empty.")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValidationError(
                f"MutationReport.threshold must be in [0, 1], got {self.threshold}."
            )
        for result in self.results:
            result.validate()
