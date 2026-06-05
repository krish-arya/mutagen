"""Coverage application service.

Wraps the :class:`CoverageCollector` port to produce coverage data and to
answer queries the orchestrator needs (e.g. which targets are covered).
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import CoverageCollector
from mutagen.core.models.coverage import CoverageReport
from mutagen.core.models.target import MutationTarget


@dataclass(slots=True)
class CoverageService:
    """Collects and applies coverage information for a run."""

    config: RunConfig
    collector: CoverageCollector

    async def collect(self) -> CoverageReport:
        """Collect coverage for the configured source paths."""
        raise NotImplementedError

    def filter_covered(
        self,
        targets: Sequence[MutationTarget],
        report: CoverageReport,
    ) -> Sequence[MutationTarget]:
        """Return only the targets that are exercised by the test suite."""
        raise NotImplementedError
