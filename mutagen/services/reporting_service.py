"""Reporting application service.

Selects and drives the configured :class:`Reporter` adapters to render a
completed run, and evaluates pass/fail against the score threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunResult


@dataclass(slots=True)
class ReportingService:
    """Renders run results and enforces the configured score threshold."""

    config: RunConfig
    reporter: Reporter

    async def render(self, result: RunResult) -> str:
        """Render ``result`` and return the output location."""
        raise NotImplementedError

    def meets_threshold(self, result: RunResult) -> bool:
        """Whether the run's mutation score satisfies the threshold."""
        raise NotImplementedError
