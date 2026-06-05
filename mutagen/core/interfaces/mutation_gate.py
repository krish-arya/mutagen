"""Mutation-gate port.

The :class:`MutationGate` is the quality gate of the pipeline: it decides
whether a target's generated tests are *good enough* by running them against
mutants of that target and computing whether they kill enough of them. A
passing gate yields a :class:`TargetOutcome`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.outcome import TargetOutcome
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
    ) -> TargetOutcome:
        """Evaluate ``tests`` against mutants of ``target``.

        Implementations generate mutants for the target, run the tests against
        each (typically via a sandbox runner), and aggregate the verdicts into
        an outcome that reflects whether the tests meet the gate's threshold.

        Args:
            target: The target whose tests are being judged.
            tests: The generated tests to evaluate.
            context: The repository snapshot the mutants are derived from.

        Returns:
            A validated :class:`TargetOutcome` summarizing the verdict.
        """
        raise NotImplementedError
