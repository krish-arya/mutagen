"""Composite :class:`Reporter` that fans out to several reporters.

The production pipeline emits both ``report.md`` and ``report.json`` (and
optionally a terminal dashboard) from one run. :class:`CompositeReporter` runs a
sequence of reporters and returns their output locations joined together.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport


@dataclass(slots=True)
class CompositeReporter(Reporter):
    """Renders a report through each of several wrapped reporters."""

    reporters: tuple[Reporter, ...] = field(default_factory=tuple)

    @property
    def format_name(self) -> str:
        return "composite"

    async def report(self, report: RunReport) -> str:
        """Run every wrapped reporter; return their locations, comma-joined."""
        locations: list[str] = []
        for reporter in self.reporters:
            locations.append(await reporter.report(report))
        return ", ".join(locations)

    @classmethod
    def of(cls, reporters: Sequence[Reporter]) -> "CompositeReporter":
        """Build a composite from a sequence of reporters."""
        return cls(reporters=tuple(reporters))
