"""Filesystem-backed :class:`RunRepository` adapter.

Serializes completed runs to disk (via the artifact store) so they can be
listed and retrieved for historical comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from mutagen.core.interfaces import ArtifactStore, RunRepository
from mutagen.core.models.run import RunResult


@dataclass(slots=True)
class FilesystemRunRepository(RunRepository):
    """Persists runs through an underlying :class:`ArtifactStore`."""

    store: ArtifactStore

    async def save(self, run_id: str, result: RunResult) -> None:
        raise NotImplementedError

    async def get(self, run_id: str) -> RunResult | None:
        raise NotImplementedError

    async def list_runs(self, *, limit: int = 50) -> Sequence[str]:
        raise NotImplementedError
