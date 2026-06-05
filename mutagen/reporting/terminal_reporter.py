"""Terminal :class:`Reporter` implementation.

Renders a human-readable summary of a run report to the console, including the
coverage ratio, mutation score, and total cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport


@dataclass(slots=True)
class TerminalReporter(Reporter):
    """Renders a run report to standard output."""

    use_color: bool = True

    @property
    def format_name(self) -> str:
        return "terminal"

    async def report(self, report: RunReport) -> str:
        raise NotImplementedError
