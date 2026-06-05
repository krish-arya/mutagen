"""Target-selection application service.

Wraps the :class:`TargetSelector` port and applies run-level policy (limits,
filtering) on top of the raw selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import TargetSelector
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target


@dataclass(slots=True)
class SelectionService:
    """Selects and bounds the targets processed in a run."""

    config: RunConfig
    selector: TargetSelector

    async def select(self, context: RepoContext) -> Sequence[Target]:
        """Select targets from ``context``, applying configured limits."""
        raise NotImplementedError
