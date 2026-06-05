"""Repository-ingestor port.

A :class:`RepoIngestor` turns a *source* — either a local path on disk or a
remote git URL — into an immutable
:class:`mutagen.core.models.repo.RepoContext`: acquiring the code into an
isolated working copy, discovering source and test files, resolving the target
Python version, and capturing the commit. It is the first stage of the
pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from mutagen.core.models.repo import RepoContext


class RepoIngestor(ABC):
    """Port for ingesting a repository into a :class:`RepoContext`."""

    @abstractmethod
    async def ingest(self, source: str | Path) -> RepoContext:
        """Ingest the repository identified by ``source``.

        ``source`` may be either a local filesystem path (absolute or
        relative) or a remote git URL (e.g. ``https://github.com/org/repo`` or
        ``git@github.com:org/repo.git``). Implementations acquire the code into
        an isolated working copy, discover source/test files, resolve the
        interpreter version, and capture VCS metadata, returning a validated,
        immutable snapshot. They must not mutate the *original* source.

        Args:
            source: A local path or a remote git URL.

        Returns:
            A validated :class:`RepoContext`.

        Raises:
            IngestionError: If the source cannot be acquired or read, or the
                snapshot cannot be constructed.
        """
        raise NotImplementedError
