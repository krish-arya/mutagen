"""Filesystem-backed :class:`Store` adapter.

Serializes runs and generated tests to a directory tree beneath a configured
root, enabling caching, resumption, and historical comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

from mutagen.config.run_config import StorageConfig
from mutagen.core.interfaces import Store
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.run import RunResult


@dataclass(slots=True)
class FilesystemStore(Store):
    """Persists runs and artifacts as files beneath a root directory."""

    config: StorageConfig

    def _run_path(self, run_id: str) -> Path:
        """Resolve the on-disk path for a run record."""
        return self.config.root / "runs" / f"{run_id}.json"

    async def save_run(self, result: RunResult) -> None:
        raise NotImplementedError

    async def load_run(self, run_id: str) -> RunResult | None:
        raise NotImplementedError

    async def save_generated_tests(
        self,
        run_id: str,
        tests: Sequence[GeneratedTest],
    ) -> None:
        raise NotImplementedError

    async def list_runs(self, *, limit: int = 50) -> Sequence[str]:
        raise NotImplementedError
