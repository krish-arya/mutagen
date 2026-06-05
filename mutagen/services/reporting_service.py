"""Reporting application service.

Summarizes a :class:`RunResult` into a :class:`RunReport`, drives the
configured :class:`Reporter`, and evaluates the run against the configured
coverage/score thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport, RunResult


@dataclass(slots=True)
class ReportingService:
    """Summarizes, renders, and gates a run on its thresholds."""

    config: RunConfig
    reporter: Reporter

    def summarize(self, result: RunResult) -> RunReport:
        """Derive a :class:`RunReport` from a raw :class:`RunResult`."""
        raise NotImplementedError

    async def render(self, report: RunReport) -> str:
        """Render ``report`` and return the output location."""
        raise NotImplementedError

    def meets_threshold(self, report: RunReport) -> bool:
        """Whether the report satisfies the configured score threshold."""
        raise NotImplementedError
