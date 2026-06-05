"""Run-repository port.

Persists completed runs so they can be retrieved for historical comparison,
trend reporting, and incremental analysis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.run import RunResult


class RunRepository(ABC):
    """Port for persisting and retrieving mutation-testing runs."""

    @abstractmethod
    async def save(self, run_id: str, result: RunResult) -> None:
        """Persist ``result`` under ``run_id``."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, run_id: str) -> RunResult | None:
        """Return the stored run for ``run_id``, or ``None`` if absent."""
        raise NotImplementedError

    @abstractmethod
    async def list_runs(self, *, limit: int = 50) -> Sequence[str]:
        """Return up to ``limit`` known run ids, newest first."""
        raise NotImplementedError
