"""Terminal :class:`Reporter` implementation.

Renders a run report's summary dashboard to the console. Uses ``rich`` for a
styled table when available and on a TTY, and falls back to plain text
otherwise so CI logs and piped output stay readable.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.core.interfaces import Reporter
from mutagen.core.models.run import RunReport


@dataclass(slots=True)
class TerminalReporter(Reporter):
    """Renders a run report's dashboard to standard output."""

    use_color: bool = True

    @property
    def format_name(self) -> str:
        return "terminal"

    async def report(self, report: RunReport) -> str:
        """Print the summary dashboard; return ``"terminal"``."""
        try:
            self._render_rich(report)
        except ImportError:
            self._render_plain(report)
        return "terminal"

    def _render_rich(self, report: RunReport) -> None:
        """Render with ``rich`` (raises ImportError if unavailable)."""
        from rich.console import Console
        from rich.table import Table

        console = Console(no_color=not self.use_color)
        table = Table(title=f"Mutagen Run {report.run_id} [{report.status.value}]")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        for label, value in self._rows(report):
            table.add_row(label, value)
        console.print(table)

    def _render_plain(self, report: RunReport) -> None:
        """Render with plain ``print`` (non-TTY / no rich fallback)."""
        print(f"Mutagen Run {report.run_id} [{report.status.value}]")
        for label, value in self._rows(report):
            print(f"  {label}: {value}")

    @staticmethod
    def _rows(report: RunReport) -> list[tuple[str, str]]:
        before = (
            f"{report.mutation_score_before:.0%}"
            if report.mutation_score_before is not None
            else "n/a"
        )
        return [
            ("Mutation score (before -> after)", f"{before} -> {report.mutation_score_after:.0%}"),
            ("Targets kept / discarded", f"{report.kept_targets} / {report.discarded_targets}"),
            ("Tests generated", str(report.total_tests_generated)),
            ("API cost", f"${report.cost.usd:.4f}"),
            ("Execution time", f"{report.duration_seconds:.1f}s"),
        ]
