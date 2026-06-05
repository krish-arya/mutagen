"""Markdown :class:`Reporter` implementation.

Renders an enriched :class:`RunReport` to a human-readable ``report.md`` with a
summary dashboard, the mutation-score before/after, kept vs. discarded targets,
cost and timing, and a per-target table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport, TargetStat

_logger = get_logger(__name__)


@dataclass(slots=True)
class MarkdownReporter(Reporter):
    """Renders a run report as a Markdown file."""

    output_path: Path

    @property
    def format_name(self) -> str:
        return "markdown"

    async def report(self, report: RunReport) -> str:
        """Write ``report`` as Markdown and return the output path."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(self._render(report), encoding="utf-8")
        _logger.info(
            "markdown report written",
            extra={"context": {"path": str(self.output_path)}},
        )
        return str(self.output_path)

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _render(self, report: RunReport) -> str:
        sections = [
            self._header(report),
            self._summary(report),
            self._score(report),
            self._targets_table(report),
            self._notes(report),
        ]
        return "\n\n".join(s for s in sections if s).rstrip() + "\n"

    @staticmethod
    def _header(report: RunReport) -> str:
        return (
            f"# Mutagen Report — `{report.run_id}`\n\nStatus: **{report.status.value}**"
        )

    @staticmethod
    def _summary(report: RunReport) -> str:
        c = report.cost
        return "\n".join(
            [
                "## Summary",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                f"| Targets processed | {report.total_targets} |",
                f"| Kept | {report.kept_targets} |",
                f"| Discarded | {report.discarded_targets} |",
                f"| Tests generated | {report.total_tests_generated} |",
                f"| Coverage ratio | {report.coverage_ratio:.0%} |",
                f"| API cost | ${c.usd:.4f} |",
                f"| Tokens (in/out) | {c.input_tokens:,} / {c.output_tokens:,} |",
                f"| LLM requests | {c.requests} |",
                f"| Execution time | {report.duration_seconds:.1f}s |",
            ]
        )

    @staticmethod
    def _score(report: RunReport) -> str:
        before = (
            f"{report.mutation_score_before:.0%}"
            if report.mutation_score_before is not None
            else "n/a"
        )
        after = f"{report.mutation_score_after:.0%}"
        delta = (
            f"{report.score_delta:+.0%}" if report.score_delta is not None else "n/a"
        )
        return "\n".join(
            [
                "## Mutation Score",
                "",
                "| Before | After | Δ |",
                "| --- | --- | --- |",
                f"| {before} | {after} | {delta} |",
            ]
        )

    @classmethod
    def _targets_table(cls, report: RunReport) -> str:
        if not report.target_stats:
            return ""
        rows = [
            "## Targets",
            "",
            "| Target | Status | Kept | Tests | Score | Cost |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for stat in report.target_stats:
            rows.append(cls._target_row(stat))
        return "\n".join(rows)

    @staticmethod
    def _target_row(stat: TargetStat) -> str:
        kept = "✅" if stat.kept else "❌"
        return (
            f"| `{stat.qualified_name}` | {stat.status.value} | {kept} | "
            f"{stat.tests_generated} | {stat.mutation_score:.0%} | "
            f"${stat.cost.usd:.4f} |"
        )

    @staticmethod
    def _notes(report: RunReport) -> str:
        if not report.notes:
            return ""
        lines = ["## Notes", ""]
        lines.extend(f"- {note}" for note in report.notes)
        return "\n".join(lines)
