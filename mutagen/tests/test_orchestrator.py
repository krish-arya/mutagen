"""Orchestration tests using mocks.

Mock ports and services stand in for ingestion, selection, generation,
sandbox, gate, reporting, and persistence, so the orchestrator's control flow —
queue management, repair/strengthening loops, budget enforcement, resume, and
immediate per-target persistence — is verified in isolation, with no real
subprocesses or LLM calls.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mutagen.config.run_config import OrchestratorConfig, RunConfig
from mutagen.core.models.checkpoint import RunCheckpoint, TargetCheckpoint
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.location import SourceSpan
from mutagen.core.models.mutation_report import MutationReport
from mutagen.core.models.outcome import (
    MutationResult,
    MutationVerdict,
    OutcomeStatus,
    TargetOutcome,
)
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.run import RunStatus
from mutagen.core.models.target import Target, TargetKind
from mutagen.core.models.test_run import RunnerStatus, SandboxResult
from mutagen.core.state_machine import RunState, TargetState
from mutagen.services import (
    PipelineOrchestrator,
    ProcessResult,
    TargetProcessor,
)


# --------------------------------------------------------------------------- #
# Shared fixtures / helpers
# --------------------------------------------------------------------------- #


def _target(i: int) -> Target:
    return Target(
        target_id=f"t{i}",
        qualified_name=f"pkg.mod.fn{i}",
        kind=TargetKind.FUNCTION,
        span=SourceSpan(path=Path("pkg/mod.py"), start_line=1, end_line=2),
        priority=1.0,
    )


def _context() -> RepoContext:
    return RepoContext(root=Path.cwd(), python_version="3.11")


def _test(test_id: str = "g", *, valid: bool = True, error: str = "") -> GeneratedTest:
    return GeneratedTest(
        test_id=test_id,
        target_id="t",
        module_path="tests/t.py",
        source="def test_x():\n    assert True\n",
        test_names=("test_x",),
        is_valid=valid,
        validation_error=error,
    )


def _killed(report_id: str = "m1") -> MutationReport:
    return MutationReport(
        target_id="t",
        kept=True,
        results=(
            MutationResult(report_id, MutationVerdict.KILLED, killing_test_ids=("g",)),
        ),
    )


def _survived() -> MutationReport:
    return MutationReport(
        target_id="t",
        kept=False,
        threshold=0.8,
        survivor_feedback="kill the surviving mutant",
        results=(MutationResult("m1", MutationVerdict.SURVIVED),),
    )


# --- mock ports ------------------------------------------------------------ #


class MockIngestor:
    async def ingest(self, source: str) -> RepoContext:
        return _context()


class MockSelection:
    def __init__(self, n: int) -> None:
        self._n = n

    async def select(self, context: RepoContext) -> Sequence[Target]:
        return [_target(i) for i in range(self._n)]


class MockGenerator:
    def __init__(self, batches: list[list[GeneratedTest]]) -> None:
        self._batches = list(batches)
        self.feedbacks: list[str | None] = []

    async def generate(self, target, context, inputs=None):  # type: ignore[no-untyped-def]
        self.feedbacks.append(inputs.feedback if inputs else None)
        return self._batches.pop(0) if self._batches else []


class MockSandbox:
    def __init__(self, results: list[SandboxResult]) -> None:
        self._results = list(results)

    async def run(self, context, tests, **kwargs):  # type: ignore[no-untyped-def]
        return self._results.pop(0)


class MockGate:
    def __init__(self, reports: list[MutationReport]) -> None:
        self._reports = list(reports)

    async def evaluate(self, target, tests, context):  # type: ignore[no-untyped-def]
        return self._reports.pop(0)


class MockProcessor:
    """Records targets processed and returns scripted results."""

    def __init__(self, result_for=None) -> None:  # type: ignore[no-untyped-def]
        self.processed: list[str] = []
        self._result_for = result_for or (
            lambda t: ProcessResult(
                TargetState.KEPT,
                TargetOutcome(target_id=t.target_id, status=OutcomeStatus.COVERED),
                attempts=1,
            )
        )

    async def process(self, target, context):  # type: ignore[no-untyped-def]
        self.processed.append(target.target_id)
        return self._result_for(target)


class MockReporting:
    def summarize(self, result):  # type: ignore[no-untyped-def]
        return result


class MockReporter:
    def __init__(self) -> None:
        self.reported = False

    async def report(self, report) -> str:  # type: ignore[no-untyped-def]
        self.reported = True
        return "report"


class MockStore:
    def __init__(self) -> None:
        self.saved_run = None

    async def save_run(self, result) -> None:  # type: ignore[no-untyped-def]
        self.saved_run = result

    async def load_run(self, run_id):  # type: ignore[no-untyped-def]
        return None

    async def save_generated_tests(self, run_id, tests) -> None:  # type: ignore[no-untyped-def]
        ...

    async def list_runs(self, *, limit: int = 50):  # type: ignore[no-untyped-def]
        return []


class MockCheckpointStore:
    """Records every target persisted and serves a preset run checkpoint."""

    def __init__(self, existing: RunCheckpoint | None = None) -> None:
        self._existing = existing
        self.saved_targets: list[TargetCheckpoint] = []
        self.run_checkpoint: RunCheckpoint | None = None

    async def load_checkpoint(self, run_id: str):
        return self._existing

    async def save_target(self, run_id: str, checkpoint: TargetCheckpoint) -> None:
        self.saved_targets.append(checkpoint)

    async def save_run_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        self.run_checkpoint = checkpoint


def _orchestrator(
    *,
    n_targets: int,
    processor=None,  # type: ignore[no-untyped-def]
    checkpoint=None,  # type: ignore[no-untyped-def]
    config: RunConfig | None = None,
):  # type: ignore[no-untyped-def]
    store = MockStore()
    cp = checkpoint or MockCheckpointStore()
    proc = processor or MockProcessor()
    orch = PipelineOrchestrator(
        config=config or RunConfig(project_root=Path.cwd()),
        ingestor=MockIngestor(),
        selection_service=MockSelection(n_targets),
        target_processor=proc,
        reporting_service=MockReporting(),
        reporter=MockReporter(),
        store=store,
        checkpoint_store=cp,
    )
    return orch, proc, store, cp


# --------------------------------------------------------------------------- #
# Queue management & happy path
# --------------------------------------------------------------------------- #


async def test_processes_all_targets_in_order() -> None:
    orch, proc, store, cp = _orchestrator(n_targets=3)
    result = await orch.execute("local", "run1")
    assert proc.processed == ["t0", "t1", "t2"]
    assert result.status is RunStatus.SUCCEEDED
    assert len(result.outcomes) == 3
    assert orch.state_machine.state is RunState.COMPLETED
    assert store.saved_run is result


async def test_persists_every_target_immediately() -> None:
    orch, proc, store, cp = _orchestrator(n_targets=3)
    await orch.execute("local", "run1")
    # One checkpoint saved per target, each terminal with an outcome.
    assert [c.target_id for c in cp.saved_targets] == ["t0", "t1", "t2"]
    assert all(c.is_done for c in cp.saved_targets)
    assert all(c.outcome is not None for c in cp.saved_targets)


async def test_initializes_run_checkpoint_when_new() -> None:
    orch, proc, store, cp = _orchestrator(n_targets=1)
    await orch.execute("local", "run1")
    assert cp.run_checkpoint is not None
    assert cp.run_checkpoint.run_id == "run1"


# --------------------------------------------------------------------------- #
# Budget enforcement -> partial result
# --------------------------------------------------------------------------- #


async def test_max_targets_stops_with_partial() -> None:
    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_targets=2),
    )
    orch, proc, store, cp = _orchestrator(n_targets=5, config=config)
    result = await orch.execute("local", "run1")
    assert proc.processed == ["t0", "t1"]  # stopped after the cap
    assert result.status is RunStatus.PARTIAL
    assert len(result.outcomes) == 2


async def test_cost_limit_stops_with_partial() -> None:
    from mutagen.core.models.cost import CostInfo

    # Each target reports $0.6. The budget is checked *before* each target, so
    # t0 runs (spend $0.0 -> $0.6), t1 runs (spend $0.6 < $1.0 -> $1.2), then
    # t2 sees spend $1.2 >= $1.0 and the run stops.
    def result_for(t):  # type: ignore[no-untyped-def]
        return ProcessResult(
            TargetState.KEPT,
            TargetOutcome(
                target_id=t.target_id,
                status=OutcomeStatus.COVERED,
                cost=CostInfo(usd=0.6),
            ),
            attempts=1,
        )

    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_cost_usd=1.0),
    )
    orch, proc, store, cp = _orchestrator(
        n_targets=5, processor=MockProcessor(result_for), config=config
    )
    result = await orch.execute("local", "run1")
    assert proc.processed == ["t0", "t1"]  # stopped before t2
    assert result.status is RunStatus.PARTIAL


# --------------------------------------------------------------------------- #
# Resume support
# --------------------------------------------------------------------------- #


async def test_resume_skips_done_targets() -> None:
    existing = RunCheckpoint(
        run_id="run1",
        targets={
            "t0": TargetCheckpoint(
                "t0", TargetState.KEPT,
                TargetOutcome("t0", OutcomeStatus.COVERED),
            ),
            "t1": TargetCheckpoint(
                "t1", TargetState.DISCARDED,
                TargetOutcome("t1", OutcomeStatus.UNCOVERED),
            ),
        },
    )
    cp = MockCheckpointStore(existing)
    orch, proc, store, _ = _orchestrator(n_targets=4, checkpoint=cp)
    result = await orch.execute("local", "run1")
    # Only the not-yet-done targets are processed...
    assert proc.processed == ["t2", "t3"]
    # ...but carried-forward outcomes are included in the result.
    assert len(result.outcomes) == 4
    ids = {o.target_id for o in result.outcomes}
    assert ids == {"t0", "t1", "t2", "t3"}


async def test_resume_with_all_done_processes_nothing() -> None:
    existing = RunCheckpoint(
        run_id="run1",
        targets={
            f"t{i}": TargetCheckpoint(
                f"t{i}", TargetState.KEPT,
                TargetOutcome(f"t{i}", OutcomeStatus.COVERED),
            )
            for i in range(3)
        },
    )
    cp = MockCheckpointStore(existing)
    orch, proc, store, _ = _orchestrator(n_targets=3, checkpoint=cp)
    result = await orch.execute("local", "run1")
    assert proc.processed == []
    assert len(result.outcomes) == 3
    assert result.status is RunStatus.SUCCEEDED


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #


async def test_ingest_failure_moves_run_to_failed() -> None:
    from mutagen.core.exceptions import IngestionError

    class FailingIngestor:
        async def ingest(self, source):  # type: ignore[no-untyped-def]
            raise IngestionError("cannot read repo")

    orch, _, _, _ = _orchestrator(n_targets=1)
    orch.ingestor = FailingIngestor()  # type: ignore[assignment]
    with pytest.raises(IngestionError):
        await orch.execute("local", "run1")
    assert orch.state_machine.state is RunState.FAILED


# --------------------------------------------------------------------------- #
# TargetProcessor: repair & strengthening loops (real processor, mock ports)
# --------------------------------------------------------------------------- #


def _processor(config: RunConfig, generator, sandbox, gate) -> TargetProcessor:  # type: ignore[no-untyped-def]
    return TargetProcessor(
        config=config, generator=generator, sandbox_runner=sandbox, gate=gate
    )


async def test_repair_loop_recovers_unrunnable_tests() -> None:
    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_repair_attempts=2),
    )
    gen = MockGenerator([[_test()], [_test()]])
    sandbox = MockSandbox(
        [
            SandboxResult(status=RunnerStatus.ERROR, output="ImportError"),
            SandboxResult(status=RunnerStatus.PASSED),
        ]
    )
    gate = MockGate([_killed()])
    result = await _processor(config, gen, sandbox, gate).process(
        _target(0), _context()
    )
    assert result.final_state is TargetState.KEPT
    assert result.attempts == 2  # one repair
    # The repair attempt carried the failure output as feedback.
    assert any("did not run" in (f or "") for f in gen.feedbacks)


async def test_repair_exhausted_discards_target() -> None:
    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_repair_attempts=1),
    )
    gen = MockGenerator([[_test()], [_test()]])
    sandbox = MockSandbox([SandboxResult(status=RunnerStatus.ERROR)] * 2)
    gate = MockGate([])
    result = await _processor(config, gen, sandbox, gate).process(
        _target(0), _context()
    )
    assert result.final_state is TargetState.DISCARDED
    assert result.outcome.status is OutcomeStatus.GENERATION_FAILED


async def test_strengthening_loop_kills_survivor() -> None:
    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_strengthen_attempts=2),
    )
    gen = MockGenerator([[_test()], [_test()]])
    sandbox = MockSandbox(
        [
            SandboxResult(status=RunnerStatus.PASSED),  # initial run
            SandboxResult(status=RunnerStatus.PASSED),  # strengthened run
        ]
    )
    gate = MockGate([_survived(), _killed()])
    result = await _processor(config, gen, sandbox, gate).process(
        _target(0), _context()
    )
    assert result.final_state is TargetState.KEPT
    assert any("kill the surviving" in (f or "") for f in gen.feedbacks)


async def test_strengthening_exhausted_discards() -> None:
    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_strengthen_attempts=1),
    )
    gen = MockGenerator([[_test()], [_test()]])
    sandbox = MockSandbox([SandboxResult(status=RunnerStatus.PASSED)] * 2)
    gate = MockGate([_survived(), _survived()])
    result = await _processor(config, gen, sandbox, gate).process(
        _target(0), _context()
    )
    assert result.final_state is TargetState.DISCARDED
    assert result.outcome.status is OutcomeStatus.UNCOVERED


async def test_invalid_tests_trigger_repair() -> None:
    config = RunConfig(
        project_root=Path.cwd(),
        orchestrator=OrchestratorConfig(max_repair_attempts=2),
    )
    # First batch is statically invalid; repair yields a valid one.
    gen = MockGenerator(
        [[_test(valid=False, error="syntax error")], [_test()]]
    )
    sandbox = MockSandbox([SandboxResult(status=RunnerStatus.PASSED)])
    gate = MockGate([_killed()])
    result = await _processor(config, gen, sandbox, gate).process(
        _target(0), _context()
    )
    assert result.final_state is TargetState.KEPT
    assert any("statically invalid" in (f or "") for f in gen.feedbacks)
