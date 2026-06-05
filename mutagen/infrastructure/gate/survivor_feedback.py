"""Survivor-feedback generation.

When mutants survive a target's generated tests, the gate produces a feedback
string describing what slipped through. That string is consumed by the
test-generator's ``feedback`` input on a subsequent attempt, steering it to add
assertions that would kill the survivors.

This module is pure: it formats survivors into prose, with no mutmut or
subprocess involvement.
"""

from __future__ import annotations

from collections.abc import Sequence

from mutagen.config.run_config import MutationConfig
from mutagen.core.models.outcome import MutationResult


class SurvivorFeedbackBuilder:
    """Builds re-generation feedback from surviving mutants."""

    def __init__(self, config: MutationConfig) -> None:
        self._config = config

    def build(self, survivors: Sequence[MutationResult], *, score: float) -> str:
        """Render survivors into a feedback string.

        Args:
            survivors: The mutants that escaped detection.
            score: The achieved mutation score, for context in the preamble.

        Returns:
            A feedback string, or empty if there were no survivors.
        """
        if not survivors:
            return ""

        capped = list(survivors[: self._config.max_survivors_in_feedback])
        lines: list[str] = [
            f"The current tests achieved a mutation score of {score:.0%}. "
            f"{len(survivors)} mutant(s) survived — the tests did not detect "
            f"these code changes. Add or tighten assertions so each surviving "
            f"mutation would cause a test to fail:",
            "",
        ]
        for i, mutant in enumerate(capped, start=1):
            lines.append(f"{i}. {self._describe(mutant)}")

        remaining = len(survivors) - len(capped)
        if remaining > 0:
            lines.append(f"... and {remaining} more surviving mutant(s).")

        feedback = "\n".join(lines)
        limit = self._config.max_feedback_chars
        if len(feedback) > limit:
            return feedback[:limit] + "\n... (truncated)"
        return feedback

    @staticmethod
    def _describe(mutant: MutationResult) -> str:
        """Render a single survivor into a one-line description."""
        detail = mutant.detail.strip().replace("\n", " ")
        if detail:
            # Keep the description compact; the diff is the useful part.
            snippet = detail[:200]
            return f"Mutant {mutant.mutant_id}: {snippet}"
        return f"Mutant {mutant.mutant_id} (no diff available)"
