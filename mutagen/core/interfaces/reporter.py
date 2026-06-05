"""Reporter port.

A :class:`Reporter` renders a :class:`RunReport` into a concrete output
format (terminal, JSON, HTML, …) and returns where it was written.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mutagen.core.models.run import RunReport


class Reporter(ABC):
    """Port for rendering a run report into a concrete output."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Identifier for the output format (e.g. ``"json"``, ``"html"``)."""
        raise NotImplementedError

    @abstractmethod
    async def report(self, report: RunReport) -> str:
        """Render ``report`` and return the path or location of the output.

        Args:
            report: The summarized run report to render.

        Returns:
            A string locating the rendered output (path, URL, or the rendered
            text itself for streaming reporters).
        """
        raise NotImplementedError
