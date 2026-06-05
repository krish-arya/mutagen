"""JSON :class:`Reporter` implementation.

Serializes a run result to a machine-readable JSON document, suitable for
CI consumption and historical archival.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunResult


@dataclass(slots=True)
class JsonReporter(Reporter):
    """Renders a run result as a JSON file."""

    output_path: Path

    @property
    def format_name(self) -> str:
        return "json"

    async def report(self, result: RunResult) -> str:
        raise NotImplementedError
