"""Per-target processing: drive one target through its lifecycle.

:class:`TargetProcessor` owns the :class:`TargetStateMachine` transitions for a
single target and the two improvement loops:

* **Repair loop** — if generated tests fail to run in the sandbox, feed the
  failure output back to the generator and try again, up to a configured cap.
* **Strengthening loop** — if mutants survive the gate, feed the survivor
  feedback back to the generator and try again, up to a configured cap.

It returns a :class:`ProcessResult` carrying the final target state
(``KEPT`` or ``DISCARDED``), the :class:`TargetOutcome`, and the cost spent —
the orchestrator persists and aggregates these. The processor performs no
persistence or budgeting itself; those are the orchestrator's concern.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.logging import get_logger
from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import MutagenError
from mutagen.core.interfaces import (
    MutationGate,
    SandboxRunner,
    TestGenerator,
)
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.generation import GenerationInputs
from mutagen.core.models.mutation_report import MutationReport
from mutagen.core.models.outcome import OutcomeStatus, TargetOutcome
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target
from mutagen.core.models.test_run import RunnerStatus, SandboxResult
from mutagen.core.state_machine import TargetState, TargetStateMachine

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """The outcome of processing one target through its lifecycle.

    Attributes:
        final_state: Terminal target state (``KEPT`` or ``DISCARDED``).
        outcome: The aggregated :class:`TargetOutcome` for the target.
        attempts: Total generation attempts spent (initial + loops).
    """

    final_state: TargetState
    outcome: TargetOutcome
    attempts: int


@dataclass(slots=True)
class TargetProcessor:
    """Processes a single target: generate, run, gate, with repair/strengthen."""

    config: RunConfig
    generator: TestGenerator
    sandbox_runner: SandboxRunner
    gate: MutationGate

    async def process(
        self, target: Target, context: RepoContext
    ) -> ProcessResult:
        """Drive ``target`` through its lifecycle and return the result.

        The state machine advances SELECTED -> GENERATED -> RAN -> MUTATED ->
        {KEPT, DISCARDED}. Any irrecoverable error or exhausted loop discards
        the target with an explanatory outcome.
        """
        machine = TargetStateMachine()
        cost = CostInfo.zero()
        attempts = 0

        try:
            tests, gen_cost, attempts = await self._generate_runnable(
                target, context, machine
            )
            cost = cost.combine(gen_cost)
            if tests is None:
                return self._discard(
                    target, machine, cost, attempts,
                    OutcomeStatus.GENERATION_FAILED,
                    "Could not generate runnable tests.",
                )

            # MUTATED: gate the runnable tests, strengthening on survivors.
            report, gate_cost, extra_attempts = await self._gate_with_strengthen(
                target, context, tests, machine
            )
            cost = cost.combine(gate_cost)
            attempts += extra_attempts
            return self._finalize(target, machine, report, cost, attempts, tests)
        except MutagenError as exc:
            _logger.warning(
                "target processing failed",
                extra={"context": {"target": target.qualified_name,
                                   "error": str(exc)}},
            )
            return self._discard(
                target, machine, cost, attempts,
                OutcomeStatus.GENERATION_FAILED, str(exc),
            )

    # ------------------------------------------------------------------ #
    # GENERATED + RAN: generate, run, repair loop
    # ------------------------------------------------------------------ #

    async def _generate_runnable(
        self,
        target: Target,
        context: RepoContext,
        machine: TargetStateMachine,
    ) -> tuple[tuple[GeneratedTest, ...] | None, CostInfo, int]:
        """Generate tests and repair until they run, or the cap is hit.

        Returns ``(tests, cost, attempts)`` with ``tests`` set once a runnable
        suite is produced, or ``None`` if repair was exhausted.
        """
        cost = CostInfo.zero()
        feedback = ""
        max_repairs = self.config.orchestrator.max_repair_attempts
        attempts = 0

        for _ in range(max_repairs + 1):
            inputs = GenerationInputs(feedback=feedback) if feedback else None
            tests = tuple(
                await self.generator.generate(target, context, inputs)
            )
            attempts += 1
            cost = cost.combine(self._tests_cost(tests))
            # Advance to GENERATED once, the first time we have any output.
            if machine.state is TargetState.SELECTED:
                machine.transition_to(TargetState.GENERATED)

            runnable = tuple(t for t in tests if t.is_valid)
            if not runnable:
                feedback = self._invalid_feedback(tests)
                continue

            result = await self.sandbox_runner.run(context, runnable)
            # Advance to RAN once, the first time a suite actually executes.
            if machine.state is TargetState.GENERATED:
                machine.transition_to(TargetState.RAN)

            if result.status in (RunnerStatus.PASSED, RunnerStatus.FAILED):
                # The suite executed; FAILED here means a test asserts wrongly,
                # which is still "runnable" — the gate will judge quality.
                return runnable, cost, attempts
            # ERROR/TIMEOUT => not runnable; repair with the captured output.
            feedback = self._repair_feedback(result)

        return None, cost, attempts

    # ------------------------------------------------------------------ #
    # MUTATED: gate, strengthening loop
    # ------------------------------------------------------------------ #

    async def _gate_with_strengthen(
        self,
        target: Target,
        context: RepoContext,
        tests: tuple[GeneratedTest, ...],
        machine: TargetStateMachine,
    ) -> tuple[MutationReport, CostInfo, int]:
        """Gate the tests, strengthening on survivors until kept or capped."""
        cost = CostInfo.zero()
        max_strengthen = self.config.orchestrator.max_strengthen_attempts
        current = tests
        report = await self.gate.evaluate(target, current, context)
        machine.transition_to(TargetState.MUTATED)
        extra_attempts = 0

        for _ in range(max_strengthen):
            if report.kept or not report.survivor_feedback:
                break
            inputs = GenerationInputs(feedback=report.survivor_feedback)
            regenerated = tuple(
                await self.generator.generate(target, context, inputs)
            )
            extra_attempts += 1
            cost = cost.combine(self._tests_cost(regenerated))
            runnable = tuple(t for t in regenerated if t.is_valid)
            if not runnable:
                break
            # Re-run to confirm the strengthened suite still executes.
            run = await self.sandbox_runner.run(context, runnable)
            if run.status not in (RunnerStatus.PASSED, RunnerStatus.FAILED):
                break
            current = runnable
            report = await self.gate.evaluate(target, current, context)

        return report, cost, extra_attempts

    # ------------------------------------------------------------------ #
    # KEPT / DISCARDED
    # ------------------------------------------------------------------ #

    def _finalize(
        self,
        target: Target,
        machine: TargetStateMachine,
        report: MutationReport,
        cost: CostInfo,
        attempts: int,
        tests: tuple[GeneratedTest, ...],
    ) -> ProcessResult:
        """Make the keep/discard decision from the gate report."""
        outcome = TargetOutcome(
            target_id=target.target_id,
            status=OutcomeStatus.COVERED if report.kept else OutcomeStatus.UNCOVERED,
            generated_test_ids=tuple(t.test_id for t in tests),
            mutation_results=report.results,
            cost=cost,
            detail=report.detail,
        )
        outcome.validate()
        if report.kept:
            machine.transition_to(TargetState.KEPT)
        else:
            machine.transition_to(TargetState.DISCARDED)
        return ProcessResult(machine.state, outcome, attempts)

    def _discard(
        self,
        target: Target,
        machine: TargetStateMachine,
        cost: CostInfo,
        attempts: int,
        status: OutcomeStatus,
        detail: str,
    ) -> ProcessResult:
        """Discard the target with an explanatory outcome."""
        outcome = TargetOutcome(
            target_id=target.target_id,
            status=status,
            cost=cost,
            detail=detail,
        )
        outcome.validate()
        machine.transition_to(TargetState.DISCARDED)
        return ProcessResult(TargetState.DISCARDED, outcome, attempts)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tests_cost(tests: tuple[GeneratedTest, ...]) -> CostInfo:
        """Sum the generation cost across a batch of tests."""
        total = CostInfo.zero()
        for test in tests:
            total = total.combine(test.cost)
        return total

    @staticmethod
    def _repair_feedback(result: SandboxResult) -> str:
        """Build repair feedback from a failed sandbox run."""
        return (
            "The generated tests did not run successfully "
            f"({result.status.value}). Fix them so they execute. Output:\n"
            f"{result.output}"
        )

    @staticmethod
    def _invalid_feedback(tests: tuple[GeneratedTest, ...]) -> str:
        """Build repair feedback from statically-invalid generated tests."""
        reasons = "; ".join(
            t.validation_error for t in tests if t.validation_error
        )
        return (
            "The generated tests were statically invalid. "
            f"Fix these problems: {reasons or 'unknown validation error'}."
        )
