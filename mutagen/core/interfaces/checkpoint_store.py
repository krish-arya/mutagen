"""Checkpoint-store port.

Persists per-target progress so a run can resume after interruption. Distinct
from :class:`mutagen.core.interfaces.store.Store` (final artifacts), this port
is the *progress* boundary: the orchestrator records each target the instant it
finishes, and on resume loads the run checkpoint to skip work already done.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mutagen.core.models.checkpoint import RunCheckpoint, TargetCheckpoint


class CheckpointStore(ABC):
    """Port for persisting and retrieving resumable run progress."""

    @abstractmethod
    async def load_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        """Return the saved checkpoint for ``run_id``, or ``None`` if none.

        Raises:
            RepositoryError: If retrieval fails for reasons other than absence.
        """
        raise NotImplementedError

    @abstractmethod
    async def save_target(self, run_id: str, checkpoint: TargetCheckpoint) -> None:
        """Persist a single target's checkpoint immediately.

        Called the moment a target reaches a terminal state, so an interrupted
        run loses at most the in-flight target.

        Args:
            run_id: Identifier of the run the target belongs to.
            checkpoint: The target checkpoint to persist (upserted by id).

        Raises:
            RepositoryError: If the checkpoint cannot be persisted.
        """
        raise NotImplementedError

    @abstractmethod
    async def save_run_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        """Persist the whole run checkpoint (e.g. start-of-run metadata).

        Args:
            checkpoint: The run checkpoint to persist (upserted by run id).

        Raises:
            RepositoryError: If the checkpoint cannot be persisted.
        """
        raise NotImplementedError
