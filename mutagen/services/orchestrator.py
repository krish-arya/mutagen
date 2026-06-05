"""Pipeline orchestration service.

The orchestrator drives a complete test-generation run through the lifecycle
defined by :class:`RunStateMachine`: ingest the repo, select targets, generate
tests, gate them against mutants, report, and persist. It owns sequencing —
not the work itself, which it delegates to ports and collaborating services.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import RepoIngestor, Reporter, Store
from mutagen.core.models.run import RunResult
from mutagen.core.state_machine import RunStateMachine
from mutagen.services.generation_service import GenerationService
from mutagen.services.reporting_service import ReportingService
from mutagen.services.selection_service import SelectionService


@dataclass(slots=True)
class PipelineOrchestrator:
    """Coordinates the phases of a single test-generation run."""

    config: RunConfig
    ingestor: RepoIngestor
    selection_service: SelectionService
    generation_service: GenerationService
    reporting_service: ReportingService
    reporter: Reporter
    store: Store
    state_machine: RunStateMachine

    async def execute(self, run_id: str) -> RunResult:
        """Execute the full pipeline for ``run_id``.

        Walks the state machine from initialization through reporting,
        delegating each phase, and persists the final result via the store.

        Args:
            run_id: Stable identifier for this run.

        Returns:
            The aggregated, validated :class:`RunResult`.
        """
        raise NotImplementedError
