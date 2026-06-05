"""Coverage measurement and extraction via ``coverage.py``.

:class:`CoverageAnalyzer` runs the project's test suite under ``coverage.py``,
emits a JSON report, and parses it into a :class:`ProjectCoverage` mapping of
file path to the set of executed lines. Running the suite is delegated to the
subprocess-safe :class:`CommandRunner`; parsing is a pure function over the
report and is exercised directly by tests without invoking coverage.

The analyzer is tolerant of a missing or empty suite: rather than failing the
whole run, it returns empty coverage so the ranker can still surface every
function as fully uncovered (and therefore high priority).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import CoverageError
from mutagen.infrastructure.process import CommandError, CommandRunner

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FileCoverage:
    """Executed-line data for a single source file.

    Attributes:
        path: Repo-relative path to the source file.
        executed_lines: 1-based line numbers that the test suite executed.
        missing_lines: 1-based executable line numbers that were not executed.
    """

    path: Path
    executed_lines: frozenset[int] = field(default_factory=frozenset)
    missing_lines: frozenset[int] = field(default_factory=frozenset)

    @property
    def executable_lines(self) -> frozenset[int]:
        """All executable lines (executed plus missing)."""
        return self.executed_lines | self.missing_lines

    def covered(self, line: int) -> bool:
        """Whether ``line`` was executed."""
        return line in self.executed_lines


@dataclass(frozen=True, slots=True)
class ProjectCoverage:
    """Whole-project coverage keyed by repo-relative path."""

    files: dict[Path, FileCoverage] = field(default_factory=dict)

    def for_file(self, path: Path) -> FileCoverage | None:
        """Return coverage for ``path``, or ``None`` if unmeasured."""
        return self.files.get(path)

    @property
    def is_empty(self) -> bool:
        """Whether any file coverage was recorded."""
        return not self.files


class CoverageAnalyzer:
    """Measures and extracts line coverage for a repository.

    Args:
        config: The run configuration.
        runner: Subprocess runner for invoking coverage; injected for tests.
            When ``None`` a default runner is constructed.
    """

    def __init__(
        self, config: RunConfig, runner: CommandRunner | None = None
    ) -> None:
        self._config = config
        self._runner = runner or CommandRunner(
            default_timeout_seconds=config.ingest.command_timeout_seconds
        )

    async def analyze(
        self, root: Path, *, python: Path | None = None
    ) -> ProjectCoverage:
        """Run the suite under coverage and return executed-line data.

        Args:
            root: Absolute path to the repository root.
            python: Interpreter to run coverage with; defaults to ``python``
                resolved from the environment.

        Returns:
            A :class:`ProjectCoverage`. Empty when no tests were collected.

        Raises:
            CoverageError: If coverage runs but its report cannot be produced
                or parsed.
        """
        interpreter = str(python) if python is not None else "python"
        report_path = root / ".mutagen-coverage.json"

        await self._run_suite(interpreter, root)
        await self._export_json(interpreter, root, report_path)
        return self.parse_report_file(report_path, root)

    async def _run_suite(self, interpreter: str, root: Path) -> None:
        """Execute ``coverage run -m pytest``; tolerate the no-tests case."""
        result = await self._runner.run(
            [interpreter, "-m", "coverage", "run", "-m", "pytest"],
            cwd=root,
            check=False,
        )
        # pytest exit code 5 == "no tests collected"; not a coverage failure.
        if result.returncode not in (0, 1, 5):
            _logger.warning(
                "coverage run reported failures",
                extra={
                    "context": {
                        "returncode": result.returncode,
                        "stderr_tail": result.stderr[-500:],
                    }
                },
            )

    async def _export_json(
        self, interpreter: str, root: Path, report_path: Path
    ) -> None:
        """Export the collected data to a JSON report."""
        try:
            await self._runner.run(
                [
                    interpreter,
                    "-m",
                    "coverage",
                    "json",
                    "-o",
                    str(report_path),
                ],
                cwd=root,
                check=True,
            )
        except CommandError as exc:
            raise CoverageError(
                f"Failed to export coverage JSON report: {exc}"
            ) from exc

    def parse_report_file(
        self, report_path: Path, root: Path
    ) -> ProjectCoverage:
        """Parse a ``coverage.py`` JSON report file into coverage data.

        Args:
            report_path: Path to the JSON report.
            root: Repository root, used to relativize file paths.

        Returns:
            The parsed :class:`ProjectCoverage`.

        Raises:
            CoverageError: If the report is missing or malformed.
        """
        try:
            raw = report_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CoverageError(
                f"Coverage report not found at {report_path}: {exc}"
            ) from exc
        return self.parse_report(raw, root)

    def parse_report(self, raw: str, root: Path) -> ProjectCoverage:
        """Parse a ``coverage.py`` JSON document into coverage data.

        Args:
            raw: The JSON report text.
            root: Repository root, used to relativize file paths.

        Returns:
            The parsed :class:`ProjectCoverage`.

        Raises:
            CoverageError: If the JSON is invalid or lacks a ``files`` section.
        """
        try:
            document: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CoverageError(f"Invalid coverage JSON: {exc}") from exc
        if not isinstance(document, dict) or "files" not in document:
            raise CoverageError(
                "Coverage JSON missing required 'files' section."
            )

        files: dict[Path, FileCoverage] = {}
        for filename, data in document["files"].items():
            rel = self._relativize(Path(filename), root)
            summary = data if isinstance(data, dict) else {}
            files[rel] = FileCoverage(
                path=rel,
                executed_lines=frozenset(
                    self._as_ints(summary.get("executed_lines", []))
                ),
                missing_lines=frozenset(
                    self._as_ints(summary.get("missing_lines", []))
                ),
            )
        return ProjectCoverage(files=files)

    @staticmethod
    def _relativize(path: Path, root: Path) -> Path:
        """Make ``path`` relative to ``root`` when possible."""
        if not path.is_absolute():
            return path
        try:
            return path.relative_to(root)
        except ValueError:
            return path

    @staticmethod
    def _as_ints(values: Any) -> list[int]:
        """Coerce a JSON line list into ints, dropping anything non-integral."""
        if not isinstance(values, list):
            return []
        return [v for v in values if isinstance(v, int)]
