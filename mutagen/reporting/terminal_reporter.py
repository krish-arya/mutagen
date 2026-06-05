"""Terminal :class:`Reporter` implementation.

Renders a human-readable summary of a run to the console, including the
mutation score and a listing of surviving mutants.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunResult


@dataclass(slots=True)
class TerminalReporter(Reporter):
    """Renders a run result to standard output."""

    use_color: bool = True

    @property
    def format_name(self) -> str:
        return "terminal"

    async def report(self, result: RunResult) -> str:
        raise NotImplementedError
