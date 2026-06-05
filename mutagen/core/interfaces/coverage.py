"""Coverage-collection port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from collections.abc import Sequence

from mutagen.core.models.coverage import CoverageReport


class CoverageCollector(ABC):
    """Port for measuring which source lines the test suite executes."""

    @abstractmethod
    async def collect(
        self,
        project_root: Path,
        targets: Sequence[Path],
    ) -> CoverageReport:
        """Run the test suite under coverage and return a report.

        Args:
            project_root: Root directory of the project under test.
            targets: Source files to measure coverage for.

        Returns:
            A :class:`CoverageReport` describing executed lines.
        """
        raise NotImplementedError
