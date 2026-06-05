"""Mutation-gate port.

The :class:`MutationGate` is the quality gate of the pipeline: it decides
whether a target's generated tests are *good enough* by running them against
mutants of that target and computing whether they kill enough of them. It
yields a :class:`MutationReport` carrying the score, the surviving mutants,
the keep/reject decision, and feedback for a re-generation attempt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.mutation_report import MutationReport
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target


class MutationGate(ABC):
    """Port for validating generated tests against mutants of a target."""

    @abstractmethod
    async def evaluate(
        self,
        target: Target,
        tests: Sequence[GeneratedTest],
        context: RepoContext,
    ) -> MutationReport:
        """Evaluate ``tests`` against mutants of ``target``.

        Implementations mutate the target, run the tests against each mutant
        in isolation, and aggregate the verdicts into a report whose
        :attr:`MutationReport.kept` flag reflects whether the mutation score
        met the configured threshold.

        Args:
            target: The target whose tests are being judged.
            tests: The generated tests to evaluate.
            context: The repository snapshot the mutants are derived from.

        Returns:
            A validated :class:`MutationReport` summarizing the verdict,
            surviving mutants, decision, and survivor feedback.

        Raises:
            MutationGateError: If the mutation run cannot be executed.
        """
        raise NotImplementedError
