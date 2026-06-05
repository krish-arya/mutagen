"""Tests for the SQLite store and checkpoint store."""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.core.models.checkpoint import RunCheckpoint, TargetCheckpoint
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.outcome import (
    MutationResult,
    MutationVerdict,
    OutcomeStatus,
    TargetOutcome,
)
from mutagen.core.models.run import RunResult, RunStatus
from mutagen.core.state_machine import TargetState
from mutagen.infrastructure.store import (
    SqliteCheckpointStore,
    SqliteStore,
    open_database,
)


@pytest.fixture
def db(tmp_path: Path):  # type: ignore[no-untyped-def]
    return open_database(tmp_path / "mutagen.db")


def _outcome(target_id: str, status: OutcomeStatus) -> TargetOutcome:
    return TargetOutcome(
        target_id=target_id,
        status=status,
        generated_test_ids=("g0",),
        mutation_results=(
            MutationResult("m1", MutationVerdict.KILLED, killing_test_ids=("g0",)),
        ),
        cost=CostInfo(input_tokens=10, output_tokens=5, usd=0.01, requests=1),
    )


def _result() -> RunResult:
    return RunResult(
        run_id="r1",
        status=RunStatus.SUCCEEDED,
        outcomes=(
            _outcome("t0", OutcomeStatus.COVERED),
            _outcome("t1", OutcomeStatus.UNCOVERED),
        ),
        cost=CostInfo(usd=0.02, requests=2),
        duration_seconds=5.0,
        started_at=100.0,
        finished_at=105.0,
    )


async def test_save_and_load_run(db) -> None:  # type: ignore[no-untyped-def]
    store = SqliteStore(db)
    await store.save_run(_result())
    loaded = await store.load_run("r1")
    assert loaded is not None
    loaded.validate()
    assert loaded.run_id == "r1"
    assert loaded.status is RunStatus.SUCCEEDED
    assert len(loaded.outcomes) == 2
    assert loaded.outcomes[0].status is OutcomeStatus.COVERED
    assert loaded.outcomes[0].mutation_results[0].verdict is MutationVerdict.KILLED
    assert loaded.cost.usd == 0.02


async def test_load_missing_run_returns_none(db) -> None:  # type: ignore[no-untyped-def]
    assert await SqliteStore(db).load_run("nope") is None


async def test_save_run_is_idempotent(db) -> None:  # type: ignore[no-untyped-def]
    store = SqliteStore(db)
    await store.save_run(_result())
    await store.save_run(_result())  # overwrite, not duplicate
    assert await store.list_runs() == ["r1"]


async def test_list_runs_newest_first(db) -> None:  # type: ignore[no-untyped-def]
    store = SqliteStore(db)
    await store.save_run(
        RunResult(run_id="old", status=RunStatus.SUCCEEDED, started_at=1.0)
    )
    await store.save_run(
        RunResult(run_id="new", status=RunStatus.SUCCEEDED, started_at=2.0)
    )
    assert await store.list_runs() == ["new", "old"]


async def test_save_generated_tests(db) -> None:  # type: ignore[no-untyped-def]
    store = SqliteStore(db)
    test = GeneratedTest(
        test_id="g0", target_id="t0", module_path="tests/t.py",
        source="def test_x():\n    assert True\n", test_names=("test_x",),
    )
    await store.save_generated_tests("r1", [test])  # must not raise


async def test_checkpoint_round_trip(db) -> None:  # type: ignore[no-untyped-def]
    cp = SqliteCheckpointStore(db)
    await cp.save_run_checkpoint(
        RunCheckpoint(run_id="r1", started_at=100.0, cost=CostInfo(usd=0.5))
    )
    await cp.save_target(
        "r1",
        TargetCheckpoint(
            "t0", TargetState.KEPT, _outcome("t0", OutcomeStatus.COVERED), 2
        ),
    )
    loaded = await cp.load_checkpoint("r1")
    assert loaded is not None
    loaded.validate()
    assert loaded.started_at == 100.0
    assert loaded.cost.usd == 0.5
    assert loaded.is_target_done("t0")
    assert loaded.targets["t0"].state is TargetState.KEPT
    assert loaded.targets["t0"].attempts == 2


async def test_checkpoint_missing_returns_none(db) -> None:  # type: ignore[no-untyped-def]
    assert await SqliteCheckpointStore(db).load_checkpoint("nope") is None


async def test_save_target_upserts(db) -> None:  # type: ignore[no-untyped-def]
    cp = SqliteCheckpointStore(db)
    await cp.save_run_checkpoint(RunCheckpoint(run_id="r1", started_at=1.0))
    await cp.save_target(
        "r1",
        TargetCheckpoint(
            "t0", TargetState.KEPT, _outcome("t0", OutcomeStatus.COVERED), 1
        ),
    )
    # Re-save the same target with different state -> upsert, not duplicate.
    await cp.save_target(
        "r1",
        TargetCheckpoint(
            "t0", TargetState.DISCARDED, _outcome("t0", OutcomeStatus.UNCOVERED), 3
        ),
    )
    loaded = await cp.load_checkpoint("r1")
    assert len(loaded.targets) == 1
    assert loaded.targets["t0"].state is TargetState.DISCARDED
    assert loaded.targets["t0"].attempts == 3
