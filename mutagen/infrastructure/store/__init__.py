"""Store adapters implementing :class:`Store` and :class:`CheckpointStore`.

* :class:`FilesystemStore` — JSON files under a root directory.
* :class:`SqliteStore` / :class:`SqliteCheckpointStore` — SQLite-backed run
  persistence and resumable per-target checkpoints.
"""

from mutagen.infrastructure.store.filesystem_store import FilesystemStore
from mutagen.infrastructure.store.sqlite_store import (
    SqliteCheckpointStore,
    SqliteStore,
    open_database,
)

__all__ = [
    "FilesystemStore",
    "SqliteStore",
    "SqliteCheckpointStore",
    "open_database",
]
