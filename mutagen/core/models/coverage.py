"""Coverage domain models.

Coverage data is used to focus mutation on lines that are actually exercised
by the test suite, dramatically reducing wasted work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileCoverage:
    """Line coverage for a single source file.

    Attributes:
        path: Path to the covered source file.
        covered_lines: Set of 1-based line numbers that were executed.
        tests_by_line: Mapping of line number to the test node ids that
            exercised it, when per-test coverage is available.
    """

    path: Path
    covered_lines: frozenset[int] = field(default_factory=frozenset)
    tests_by_line: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def covers(self, line: int) -> bool:
        """Whether the given line was executed by any test."""
        return line in self.covered_lines


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Whole-project coverage, keyed by file path."""

    files: dict[Path, FileCoverage] = field(default_factory=dict)

    def for_file(self, path: Path) -> FileCoverage | None:
        """Return coverage for a file, or ``None`` if not measured."""
        return self.files.get(path)
