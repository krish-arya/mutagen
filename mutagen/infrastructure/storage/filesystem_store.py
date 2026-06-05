"""Filesystem-backed :class:`ArtifactStore` adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.config.run_config import StorageConfig
from mutagen.core.interfaces import ArtifactStore


@dataclass(slots=True)
class FilesystemArtifactStore(ArtifactStore):
    """Stores artifacts as files beneath a configured root directory."""

    config: StorageConfig

    def _path_for(self, key: str) -> Path:
        """Resolve the on-disk path for an artifact ``key``."""
        return self.config.root / key

    async def write(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    async def read(self, key: str) -> bytes:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError
