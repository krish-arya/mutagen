"""``coverage.py``-backed :class:`CoverageCollector` adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

from mutagen.config.run_config import CoverageConfig
from mutagen.core.interfaces import CoverageCollector
from mutagen.core.models.coverage import CoverageReport


@dataclass(slots=True)
class CoveragePyCollector(CoverageCollector):
    """Collects line coverage by driving ``coverage.py``."""

    config: CoverageConfig

    async def collect(
        self,
        project_root: Path,
        targets: Sequence[Path],
    ) -> CoverageReport:
        raise NotImplementedError
