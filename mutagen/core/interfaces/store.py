"""Store port.

The :class:`Store` persists pipeline artifacts and run results so they can be
retrieved across runs — for caching generated tests, resuming, and historical
comparison. It is a typed, run-aware persistence boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.run import RunResult


class Store(ABC):
    """Port for persisting and retrieving runs and generated artifacts."""

    @abstractmethod
    async def save_run(self, result: RunResult) -> None:
        """Persist a completed run, keyed by its ``run_id``.

        Args:
            result: The validated run result to persist. Overwrites any
                existing record with the same id.

        Raises:
            RepositoryError: If the run cannot be persisted.
        """
        raise NotImplementedError

    @abstractmethod
    async def load_run(self, run_id: str) -> RunResult | None:
        """Return the stored run for ``run_id``, or ``None`` if absent.

        Raises:
            RepositoryError: If retrieval fails for reasons other than absence.
        """
        raise NotImplementedError

    @abstractmethod
    async def save_generated_tests(
        self,
        run_id: str,
        tests: Sequence[GeneratedTest],
    ) -> None:
        """Persist generated tests produced during a run.

        Args:
            run_id: Identifier of the run the tests belong to.
            tests: The generated tests to persist.

        Raises:
            RepositoryError: If the artifacts cannot be persisted.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_runs(self, *, limit: int = 50) -> Sequence[str]:
        """Return up to ``limit`` known run ids, newest first.

        Raises:
            RepositoryError: If the listing cannot be retrieved.
        """
        raise NotImplementedError
