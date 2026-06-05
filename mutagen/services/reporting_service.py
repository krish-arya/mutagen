"""Reporting application service.

Summarizes a :class:`RunResult` into an enriched :class:`RunReport`, drives the
configured :class:`Reporter`, and evaluates the run against the configured
score threshold. All headline numbers the reporters render — score before/after,
kept/discarded counts, cost, duration, and per-target stats — are derived here
so there is a single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import Reporter
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.outcome import OutcomeStatus, TargetOutcome
from mutagen.core.models.run import RunReport, RunResult, RunStatus, TargetStat


@dataclass(slots=True)
class ReportingService:
    """Summarizes, renders, and gates a run on its thresholds."""

    config: RunConfig
    reporter: Reporter

    def summarize(self, result: RunResult) -> RunReport:
        """Derive an enriched :class:`RunReport` from a raw :class:`RunResult`.

        Args:
            result: The aggregated run result.

        Returns:
            A validated :class:`RunReport` with the headline statistics.
        """
        stats = tuple(self._stat(o) for o in result.outcomes)
        covered = sum(1 for o in result.outcomes if self._is_covered(o))
        kept = covered  # a kept target is one that reached COVERED status
        discarded = len(result.outcomes) - kept
        tests_generated = sum(
            len(o.generated_test_ids) for o in result.outcomes
        )

        report = RunReport(
            run_id=result.run_id,
            status=result.status,
            total_targets=len(result.outcomes),
            covered_targets=covered,
            kept_targets=kept,
            discarded_targets=discarded,
            total_tests_generated=tests_generated,
            mutation_score=self._overall_score(result),
            mutation_score_before=self._baseline_score(result),
            cost=result.cost,
            duration_seconds=result.duration_seconds,
            target_stats=stats,
            notes=self._notes(result),
        )
        report.validate()
        return report

    async def render(self, report: RunReport) -> str:
        """Render ``report`` via the reporter and return the output location."""
        return await self.reporter.report(report)

    def meets_threshold(self, report: RunReport) -> bool:
        """Whether the run's mutation score satisfies the configured threshold."""
        return report.mutation_score >= self.config.score_threshold

    # ------------------------------------------------------------------ #
    # Derivation helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_covered(outcome: TargetOutcome) -> bool:
        return outcome.status is OutcomeStatus.COVERED

    def _stat(self, outcome: TargetOutcome) -> TargetStat:
        """Build a per-target stat from an outcome."""
        return TargetStat(
            target_id=outcome.target_id,
            qualified_name=outcome.target_id,  # best available identifier
            status=outcome.status,
            kept=self._is_covered(outcome),
            tests_generated=len(outcome.generated_test_ids),
            mutation_score=outcome.mutation_score,
            cost=outcome.cost,
        )

    @staticmethod
    def _overall_score(result: RunResult) -> float:
        """Mean post-generation mutation score across scored targets."""
        scored = [
            o.mutation_score
            for o in result.outcomes
            if o.mutation_results
        ]
        if not scored:
            return 0.0
        return sum(scored) / len(scored)

    @staticmethod
    def _baseline_score(result: RunResult) -> float | None:
        """The 'before' baseline score, if any target carried one.

        The baseline (mutation score using only the repo's pre-existing tests)
        is recorded on a target's outcome metadata by the gate when feasible.
        Until baselines are measured upstream there is none to report, so this
        returns ``None`` and the reporters render 'n/a'.
        """
        # Baselines are not yet measured by the pipeline; surface None so the
        # before/after wiring is in place without inventing a placeholder.
        return None

    @staticmethod
    def _notes(result: RunResult) -> tuple[str, ...]:
        """Human-readable annotations for the report."""
        notes: list[str] = []
        if result.status is RunStatus.PARTIAL:
            notes.append(
                "Run stopped early after reaching a budget/cost limit; "
                "results are partial and the run is resumable."
            )
        return tuple(notes)
