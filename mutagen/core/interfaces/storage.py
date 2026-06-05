"""Artifact-storage port.

Abstracts where intermediate and output artifacts (diffs, logs, serialized
results) are persisted, so the engine is agnostic to local vs. remote stores.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ArtifactStore(ABC):
    """Port for reading and writing opaque artifacts by key."""

    @abstractmethod
    async def write(self, key: str, data: bytes) -> None:
        """Persist ``data`` under ``key``, overwriting any existing value."""
        raise NotImplementedError

    @abstractmethod
    async def read(self, key: str) -> bytes:
        """Return the bytes stored under ``key``.

        Raises:
            KeyError: If no artifact exists for ``key``.
        """
        raise NotImplementedError

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Whether an artifact exists for ``key``."""
        raise NotImplementedError
