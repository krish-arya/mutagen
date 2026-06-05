"""JSON :class:`Reporter` implementation.

Serializes a run report to a machine-readable JSON document, suitable for CI
consumption and historical archival.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport


@dataclass(slots=True)
class JsonReporter(Reporter):
    """Renders a run report as a JSON file."""

    output_path: Path

    @property
    def format_name(self) -> str:
        return "json"

    async def report(self, report: RunReport) -> str:
        raise NotImplementedError
