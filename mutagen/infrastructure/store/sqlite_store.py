"""SQLite-backed persistence for runs and resumable checkpoints.

Two adapters share one SQLite database:

* :class:`SqliteStore` implements :class:`mutagen.core.interfaces.store.Store`
  for final run results and generated-test artifacts.
* :class:`SqliteCheckpointStore` implements
  :class:`mutagen.core.interfaces.checkpoint_store.CheckpointStore` for
  per-target progress, enabling resume — every target is upserted the moment
  it finishes.

SQLite's API is synchronous; the async port methods run it on a worker thread
via :func:`asyncio.to_thread` so they never block the event loop. Run results
and outcomes are stored as JSON blobs, which keeps the schema small and the
domain models the single source of truth.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.core.exceptions import RepositoryError
from mutagen.core.interfaces import CheckpointStore, Store
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

_logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS run_checkpoints (
    run_id     TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    cost       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_checkpoints (
    run_id    TEXT NOT NULL,
    target_id TEXT NOT NULL,
    state     TEXT NOT NULL,
    attempts  INTEGER NOT NULL,
    outcome   TEXT,
    PRIMARY KEY (run_id, target_id)
);
CREATE TABLE IF NOT EXISTS generated_tests (
    run_id  TEXT NOT NULL,
    test_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, test_id)
);
"""


class _Database:
    """Owns the SQLite connection path and schema bootstrap."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        try:
            with closing(self._connect()) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Failed to initialize database: {exc}") from exc

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        try:
            with closing(self._connect()) as conn:
                conn.execute(sql, params)
                conn.commit()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Database write failed: {exc}") from exc

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        try:
            with closing(self._connect()) as conn:
                return list(conn.execute(sql, params).fetchall())
        except sqlite3.Error as exc:
            raise RepositoryError(f"Database read failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# JSON (de)serialization of domain models
# --------------------------------------------------------------------------- #


def _cost_to_dict(cost: CostInfo) -> dict[str, Any]:
    return {
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "usd": cost.usd,
        "requests": cost.requests,
    }


def _cost_from_dict(data: dict[str, Any]) -> CostInfo:
    return CostInfo(
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        usd=float(data.get("usd", 0.0)),
        requests=int(data.get("requests", 0)),
    )


def _outcome_to_dict(outcome: TargetOutcome) -> dict[str, Any]:
    return {
        "target_id": outcome.target_id,
        "status": outcome.status.value,
        "generated_test_ids": list(outcome.generated_test_ids),
        "mutation_results": [
            {
                "mutant_id": r.mutant_id,
                "verdict": r.verdict.value,
                "killing_test_ids": list(r.killing_test_ids),
                "duration_seconds": r.duration_seconds,
                "detail": r.detail,
            }
            for r in outcome.mutation_results
        ],
        "cost": _cost_to_dict(outcome.cost),
        "detail": outcome.detail,
    }


def _outcome_from_dict(data: dict[str, Any]) -> TargetOutcome:
    return TargetOutcome(
        target_id=data["target_id"],
        status=OutcomeStatus(data["status"]),
        generated_test_ids=tuple(data.get("generated_test_ids", [])),
        mutation_results=tuple(
            MutationResult(
                mutant_id=r["mutant_id"],
                verdict=MutationVerdict(r["verdict"]),
                killing_test_ids=tuple(r.get("killing_test_ids", [])),
                duration_seconds=r.get("duration_seconds", 0.0),
                detail=r.get("detail", ""),
            )
            for r in data.get("mutation_results", [])
        ),
        cost=_cost_from_dict(data.get("cost", {})),
        detail=data.get("detail", ""),
    )


def _run_to_dict(result: RunResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status.value,
        "outcomes": [_outcome_to_dict(o) for o in result.outcomes],
        "cost": _cost_to_dict(result.cost),
        "duration_seconds": result.duration_seconds,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
    }


def _run_from_dict(data: dict[str, Any]) -> RunResult:
    return RunResult(
        run_id=data["run_id"],
        status=RunStatus(data["status"]),
        outcomes=tuple(_outcome_from_dict(o) for o in data.get("outcomes", [])),
        cost=_cost_from_dict(data.get("cost", {})),
        duration_seconds=data.get("duration_seconds", 0.0),
        started_at=data.get("started_at", 0.0),
        finished_at=data.get("finished_at", 0.0),
    )


# --------------------------------------------------------------------------- #
# Store (final runs + artifacts)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class SqliteStore(Store):
    """SQLite-backed :class:`Store` for runs and generated tests."""

    db: _Database

    async def save_run(self, result: RunResult) -> None:
        payload = json.dumps(_run_to_dict(result))
        await asyncio.to_thread(
            self.db.execute,
            "INSERT OR REPLACE INTO runs (run_id, status, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (result.run_id, result.status.value, payload, result.started_at),
        )

    async def load_run(self, run_id: str) -> RunResult | None:
        rows = await asyncio.to_thread(
            self.db.query,
            "SELECT payload FROM runs WHERE run_id = ?",
            (run_id,),
        )
        if not rows:
            return None
        return _run_from_dict(json.loads(rows[0]["payload"]))

    async def save_generated_tests(
        self, run_id: str, tests: Sequence[GeneratedTest]
    ) -> None:
        for test in tests:
            payload = json.dumps(
                {
                    "test_id": test.test_id,
                    "target_id": test.target_id,
                    "module_path": test.module_path,
                    "source": test.source,
                    "test_names": list(test.test_names),
                    "is_valid": test.is_valid,
                    "validation_error": test.validation_error,
                }
            )
            await asyncio.to_thread(
                self.db.execute,
                "INSERT OR REPLACE INTO generated_tests (run_id, test_id, "
                "payload) VALUES (?, ?, ?)",
                (run_id, test.test_id, payload),
            )

    async def list_runs(self, *, limit: int = 50) -> Sequence[str]:
        rows = await asyncio.to_thread(
            self.db.query,
            "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [row["run_id"] for row in rows]


# --------------------------------------------------------------------------- #
# CheckpointStore (resumable progress)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class SqliteCheckpointStore(CheckpointStore):
    """SQLite-backed :class:`CheckpointStore` for resumable run progress."""

    db: _Database

    async def load_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        run_rows = await asyncio.to_thread(
            self.db.query,
            "SELECT started_at, cost FROM run_checkpoints WHERE run_id = ?",
            (run_id,),
        )
        if not run_rows:
            return None
        target_rows = await asyncio.to_thread(
            self.db.query,
            "SELECT target_id, state, attempts, outcome FROM "
            "target_checkpoints WHERE run_id = ?",
            (run_id,),
        )
        targets = {
            row["target_id"]: TargetCheckpoint(
                target_id=row["target_id"],
                state=TargetState(row["state"]),
                outcome=(
                    _outcome_from_dict(json.loads(row["outcome"]))
                    if row["outcome"]
                    else None
                ),
                attempts=row["attempts"],
            )
            for row in target_rows
        }
        return RunCheckpoint(
            run_id=run_id,
            targets=targets,
            cost=_cost_from_dict(json.loads(run_rows[0]["cost"])),
            started_at=run_rows[0]["started_at"],
        )

    async def save_target(
        self, run_id: str, checkpoint: TargetCheckpoint
    ) -> None:
        outcome = (
            json.dumps(_outcome_to_dict(checkpoint.outcome))
            if checkpoint.outcome is not None
            else None
        )
        await asyncio.to_thread(
            self.db.execute,
            "INSERT OR REPLACE INTO target_checkpoints (run_id, target_id, "
            "state, attempts, outcome) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                checkpoint.target_id,
                checkpoint.state.value,
                checkpoint.attempts,
                outcome,
            ),
        )

    async def save_run_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        await asyncio.to_thread(
            self.db.execute,
            "INSERT OR REPLACE INTO run_checkpoints (run_id, started_at, cost) "
            "VALUES (?, ?, ?)",
            (
                checkpoint.run_id,
                checkpoint.started_at,
                json.dumps(_cost_to_dict(checkpoint.cost)),
            ),
        )


def open_database(path: Path) -> _Database:
    """Open (and bootstrap) the SQLite database at ``path``."""
    return _Database(path)
