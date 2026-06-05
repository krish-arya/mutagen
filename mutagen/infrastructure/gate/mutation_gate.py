"""AST-mutation :class:`MutationGate` adapter.

Generates AST mutants for a target, runs the generated tests against each via
a :class:`SandboxRunner`, and aggregates the verdicts into a
:class:`TargetOutcome` judged against a configured kill-ratio threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import MutationGate, SandboxRunner
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.outcome import TargetOutcome
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target


@dataclass(slots=True)
class AstMutationGate(MutationGate):
    """Validates generated tests by killing AST mutants of the target."""

    config: RunConfig
    sandbox_runner: SandboxRunner

    async def evaluate(
        self,
        target: Target,
        tests: Sequence[GeneratedTest],
        context: RepoContext,
    ) -> TargetOutcome:
        raise NotImplementedError
