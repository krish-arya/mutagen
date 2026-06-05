"""JSON :class:`Reporter` implementation.

Serializes an enriched :class:`RunReport` to a machine-readable JSON document
(``report.json`` by default), suitable for CI consumption and historical
archival. The schema mirrors the report's headline fields plus per-target stats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport, TargetStat

_logger = get_logger(__name__)


@dataclass(slots=True)
class JsonReporter(Reporter):
    """Renders a run report as a JSON file."""

    output_path: Path

    @property
    def format_name(self) -> str:
        return "json"

    async def report(self, report: RunReport) -> str:
        """Write ``report`` as JSON and return the output path."""
        document = self._to_document(report)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(document, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _logger.info(
            "json report written",
            extra={"context": {"path": str(self.output_path)}},
        )
        return str(self.output_path)

    @staticmethod
    def _to_document(report: RunReport) -> dict[str, Any]:
        """Convert a report into a JSON-serializable dict."""
        return {
            "run_id": report.run_id,
            "status": report.status.value,
            "mutation_score": {
                "before": report.mutation_score_before,
                "after": report.mutation_score_after,
                "delta": report.score_delta,
            },
            "targets": {
                "total": report.total_targets,
                "kept": report.kept_targets,
                "discarded": report.discarded_targets,
                "covered": report.covered_targets,
                "coverage_ratio": report.coverage_ratio,
            },
            "tests_generated": report.total_tests_generated,
            "cost": {
                "usd": report.cost.usd,
                "input_tokens": report.cost.input_tokens,
                "output_tokens": report.cost.output_tokens,
                "requests": report.cost.requests,
            },
            "duration_seconds": report.duration_seconds,
            "target_stats": [
                JsonReporter._stat_to_dict(s) for s in report.target_stats
            ],
            "notes": list(report.notes),
        }

    @staticmethod
    def _stat_to_dict(stat: TargetStat) -> dict[str, Any]:
        return {
            "target_id": stat.target_id,
            "qualified_name": stat.qualified_name,
            "status": stat.status.value,
            "kept": stat.kept,
            "tests_generated": stat.tests_generated,
            "mutation_score": stat.mutation_score,
            "cost_usd": stat.cost.usd,
        }
