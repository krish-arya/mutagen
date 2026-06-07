"""Target-selection application service.

Wraps the :class:`TargetSelector` port and applies run-level policy (limits,
filtering) on top of the raw selection.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
        """Select targets from ``context``, applying configured limits.

        Delegates ranking to the :class:`TargetSelector` port, then applies the
        run-level ``orchestrator.max_targets`` cap on top (``0`` = unlimited).
        The selector's own ``selection.max_targets`` is a selection-policy cap;
        this is the orchestration budget cap, so the smaller of the two wins.

        Returns:
            The selected targets, ordered by descending priority and bounded by
            the orchestrator's target budget.
        """
        targets = await self.selector.select(context)
        limit = self.config.orchestrator.max_targets
        if limit > 0:
            return list(targets[:limit])
        return list(targets)
