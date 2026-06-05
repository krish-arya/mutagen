"""Run orchestration service.

The orchestrator drives a complete mutation-testing run through the lifecycle
defined by :class:`RunStateMachine`, delegating each phase to a collaborating
service or port. It owns sequencing, not the work itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import Reporter, RunRepository, Sandbox, TestRunner
from mutagen.core.models.run import RunResult
from mutagen.core.state_machine import RunStateMachine
from mutagen.services.coverage_service import CoverageService
from mutagen.services.mutation_service import MutationService


@dataclass(slots=True)
class RunOrchestrator:
    """Coordinates the phases of a single mutation-testing run."""

    config: RunConfig
    coverage_service: CoverageService
    mutation_service: MutationService
    sandbox: Sandbox
    test_runner: TestRunner
    reporter: Reporter
    repository: RunRepository
    state_machine: RunStateMachine

    async def execute(self, run_id: str) -> RunResult:
        """Execute the full run identified by ``run_id``.

        Walks the state machine from initialization through reporting,
        delegating each phase, and persists the final result.

        Returns:
            The aggregated :class:`RunResult`.
        """
        raise NotImplementedError
