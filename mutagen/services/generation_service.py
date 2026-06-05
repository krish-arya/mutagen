"""Test-generation application service.

Coordinates the :class:`TestGenerator` and :class:`MutationGate` ports to turn
each target into validated tests and a :class:`TargetOutcome`, accumulating
cost as it goes.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import MutationGate, Store, TestGenerator
from mutagen.core.models.outcome import TargetOutcome
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target


@dataclass(slots=True)
class GenerationService:
    """Generates and gates tests for individual targets."""

    config: RunConfig
    generator: TestGenerator
    gate: MutationGate
    store: Store

    async def process(
        self,
        target: Target,
        context: RepoContext,
    ) -> TargetOutcome:
        """Generate tests for ``target`` and gate them, returning the outcome.

        Args:
            target: The target to generate and validate tests for.
            context: The repository snapshot under test.

        Returns:
            A validated :class:`TargetOutcome` for the target.
        """
        raise NotImplementedError
