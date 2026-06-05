"""Reporter port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mutagen.core.models.run import RunResult


class Reporter(ABC):
    """Port for rendering a run result into a human- or machine-readable form."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Identifier for the output format (e.g. ``"json"``, ``"html"``)."""
        raise NotImplementedError

    @abstractmethod
    async def report(self, result: RunResult) -> str:
        """Render ``result`` and return the path or location of the output."""
        raise NotImplementedError
