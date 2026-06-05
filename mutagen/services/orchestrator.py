"""Pipeline orchestration service.

The orchestrator drives a complete test-generation run: it ingests the repo,
selects targets, then processes each target through its lifecycle (generate →
run → mutate → keep/discard, with repair and strengthening loops), and finally
reports and persists the aggregated result.

It owns the cross-cutting concerns the per-target processor does not:

* **Queue management** — selected targets are processed in priority order,
  skipping any already completed on a prior run.
* **Budget & cost enforcement** — before each target it checks the
  :class:`BudgetTracker`; when a limit is reached it stops scheduling and
  finalizes a *partial* result (the in-flight target is allowed to finish).
* **Resume support** — progress is loaded from the :class:`CheckpointStore`;
  terminal targets are skipped and their outcomes carried forward.
* **State persistence** — every target outcome is persisted *immediately* as
  it finishes, so an interrupted run loses at most the in-flight target.

The run-level :class:`RunStateMachine` tracks the coarse phase; the per-target
:class:`TargetStateMachine` lives inside :class:`TargetProcessor`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from mutagen.config.logging import get_logger
from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import MutagenError
from mutagen.core.interfaces import CheckpointStore, RepoIngestor, Reporter, Store
from mutagen.core.models.checkpoint import (
    RunCheckpoint,
    TargetCheckpoint,
)
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.outcome import TargetOutcome
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.run import RunResult, RunStatus
from mutagen.core.models.target import Target
from mutagen.core.state_machine import RunState, RunStateMachine
from mutagen.services.budget import BudgetReason, BudgetTracker
from mutagen.services.progress import (
    ProgressEvent,
    ProgressListener,
    ProgressPhase,
)
from mutagen.services.reporting_service import ReportingService
from mutagen.services.selection_service import SelectionService
from mutagen.services.target_processor import ProcessResult, TargetProcessor

_logger = get_logger(__name__)


@dataclass(slots=True)
class PipelineOrchestrator:
    """Coordinates the phases of a single test-generation run."""

    config: RunConfig
    ingestor: RepoIngestor
    selection_service: SelectionService
    target_processor: TargetProcessor
    reporting_service: ReportingService
    reporter: Reporter
    store: Store
    checkpoint_store: CheckpointStore
    state_machine: RunStateMachine = field(default_factory=RunStateMachine)
    progress: ProgressListener | None = None

    def _emit(self, event: ProgressEvent) -> None:
        """Announce a progress event if a listener is attached."""
        if self.progress is not None:
            self.progress(event)

    async def execute(self, source: str, run_id: str) -> RunResult:
        """Execute (or resume) the run identified by ``run_id``.

        Args:
            source: Repository source (local path or git URL) to ingest.
            run_id: Stable identifier for the run; reused to resume.

        Returns:
            The aggregated, validated :class:`RunResult`. Its status is
            ``PARTIAL`` when a budget limit stopped the run early.
        """
        started = time.time()
        try:
            checkpoint = await self._load_or_init_checkpoint(run_id, started)
            context = await self._ingest(source)
            targets = await self._select(context)
            outcomes, stopped = await self._process_queue(
                run_id, context, targets, checkpoint
            )
            result = self._build_result(run_id, outcomes, checkpoint, started, stopped)
            await self._report_and_persist(result)
            self._transition(RunState.COMPLETED)
            return result
        except MutagenError as exc:
            _logger.error(
                "run failed", extra={"context": {"run_id": run_id, "error": str(exc)}}
            )
            self._safe_fail()
            raise

    # ------------------------------------------------------------------ #
    # Resume support
    # ------------------------------------------------------------------ #

    async def _load_or_init_checkpoint(
        self, run_id: str, started: float
    ) -> RunCheckpoint:
        """Load existing progress to resume, or start a fresh checkpoint."""
        existing = await self.checkpoint_store.load_checkpoint(run_id)
        if existing is not None:
            _logger.info(
                "resuming run",
                extra={
                    "context": {
                        "run_id": run_id,
                        "done_targets": sum(
                            1 for c in existing.targets.values() if c.is_done
                        ),
                    }
                },
            )
            return existing
        checkpoint = RunCheckpoint(run_id=run_id, started_at=started)
        await self.checkpoint_store.save_run_checkpoint(checkpoint)
        return checkpoint

    # ------------------------------------------------------------------ #
    # Phases: ingest, select
    # ------------------------------------------------------------------ #

    async def _ingest(self, source: str) -> RepoContext:
        self._transition(RunState.INITIALIZING)
        self._transition(RunState.INGESTING)
        self._emit(ProgressEvent(ProgressPhase.INGESTING, f"Ingesting {source}"))
        return await self.ingestor.ingest(source)

    async def _select(self, context: RepoContext) -> Sequence[Target]:
        self._transition(RunState.SELECTING_TARGETS)
        self._emit(ProgressEvent(ProgressPhase.SELECTING, "Selecting targets"))
        return await self.selection_service.select(context)

    # ------------------------------------------------------------------ #
    # Queue management + budget + per-target persistence
    # ------------------------------------------------------------------ #

    async def _process_queue(
        self,
        run_id: str,
        context: RepoContext,
        targets: Sequence[Target],
        checkpoint: RunCheckpoint,
    ) -> tuple[list[TargetOutcome], BudgetReason | None]:
        """Process targets — up to ``max_parallel_targets`` at once.

        Targets are independent (each runs in its own isolated sandbox and
        mutation workspace), so they are processed by a bounded worker pool.
        Budget/cost limits are checked atomically before each target is
        scheduled; once a limit is hit, no new targets start but those already
        in flight are allowed to finish, yielding a clean PARTIAL result.

        Every finished target is persisted immediately, so the run remains
        resumable regardless of concurrency.

        Returns the outcomes (including those carried forward from a prior run)
        and the budget reason that stopped the run early, if any.
        """
        self._transition(RunState.GENERATING_TESTS)
        budget = BudgetTracker(self.config.orchestrator, started_at=0.0)
        budget.record_cost(checkpoint.cost)

        # Carry forward outcomes already completed on a prior run.
        carried: list[TargetOutcome] = list(checkpoint.completed_outcomes)
        pending = [t for t in targets if not checkpoint.is_target_done(t.target_id)]

        limit = max(1, self.config.orchestrator.max_parallel_targets)
        semaphore = asyncio.Semaphore(limit)
        # Captures shared across workers; guarded by the budget lock or by the
        # single-threaded event loop (mutated only outside ``await`` points).
        new_outcomes: list[TargetOutcome] = []
        stop_reason: BudgetReason | None = None
        completed_baseline = len(carried)
        total = len(targets)

        async def worker(target: Target) -> None:
            try:
                self._emit(
                    ProgressEvent(
                        ProgressPhase.PROCESSING,
                        f"Processing {target.qualified_name}",
                        completed=completed_baseline + len(new_outcomes),
                        total=total,
                    )
                )
                result = await self.target_processor.process(target, context)
                await budget.record_cost_safe(result.outcome.cost)
                new_outcomes.append(result.outcome)
                await self._persist_target(run_id, result)
                self._emit(
                    ProgressEvent(
                        ProgressPhase.PROCESSING,
                        f"{result.final_state.value}: {target.qualified_name}",
                        completed=completed_baseline + len(new_outcomes),
                        total=total,
                    )
                )
            finally:
                semaphore.release()

        tasks: list[asyncio.Task[None]] = []
        for target in pending:
            # Bound the number of concurrently-running workers.
            await semaphore.acquire()
            # Atomically check the budget and reserve a target slot. If the
            # budget is spent, stop scheduling (release the slot we took).
            reason = await budget.try_reserve()
            if reason is not None:
                semaphore.release()
                stop_reason = reason
                _logger.info(
                    "budget reached; stopping",
                    extra={
                        "context": {
                            "reason": reason.value,
                            "processed": budget.processed,
                        }
                    },
                )
                break
            tasks.append(asyncio.create_task(worker(target)))

        # Let every scheduled worker finish (in-flight work always completes).
        if tasks:
            await asyncio.gather(*tasks)

        self._transition(RunState.GATING)
        return carried + new_outcomes, stop_reason

    async def _persist_target(self, run_id: str, result: ProcessResult) -> None:
        """Persist a finished target's checkpoint immediately."""
        checkpoint = TargetCheckpoint(
            target_id=result.outcome.target_id,
            state=result.final_state,
            outcome=result.outcome,
            attempts=result.attempts,
        )
        checkpoint.validate()
        await self.checkpoint_store.save_target(run_id, checkpoint)

    # ------------------------------------------------------------------ #
    # Finalize: build result, report, persist
    # ------------------------------------------------------------------ #

    def _build_result(
        self,
        run_id: str,
        outcomes: list[TargetOutcome],
        checkpoint: RunCheckpoint,
        started: float,
        stopped: BudgetReason | None,
    ) -> RunResult:
        """Aggregate outcomes into a validated :class:`RunResult`."""
        finished = time.time()
        total_cost = CostInfo.zero()
        for outcome in outcomes:
            total_cost = total_cost.combine(outcome.cost)

        status = RunStatus.PARTIAL if stopped else RunStatus.SUCCEEDED
        result = RunResult(
            run_id=run_id,
            status=status,
            outcomes=tuple(outcomes),
            cost=total_cost,
            duration_seconds=max(0.0, finished - started),
            started_at=checkpoint.started_at or started,
            finished_at=finished,
        )
        result.validate()
        return result

    async def _report_and_persist(self, result: RunResult) -> None:
        """Render the report and persist the final run result."""
        self._transition(RunState.REPORTING)
        self._emit(ProgressEvent(ProgressPhase.REPORTING, "Writing reports"))
        report = self.reporting_service.summarize(result)
        await self.reporter.report(report)
        await self.store.save_run(result)
        self._emit(ProgressEvent(ProgressPhase.DONE, f"Run {result.status.value}"))

    # ------------------------------------------------------------------ #
    # State-machine helpers
    # ------------------------------------------------------------------ #

    def _transition(self, target: RunState) -> None:
        """Advance the run state machine, tolerating idempotent re-entry."""
        if self.state_machine.state is target:
            return
        self.state_machine.transition_to(target)

    def _safe_fail(self) -> None:
        """Move the run to FAILED if the transition is legal."""
        if self.state_machine.can_transition(RunState.FAILED):
            self.state_machine.transition_to(RunState.FAILED)
