"""Source-location value objects.

These model positions within source files. They are used throughout the
domain to anchor mutations, coverage data, and diagnostics to concrete
points in the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A single point in a source file.

    Attributes:
        path: Absolute or project-relative path to the source file.
        line: 1-based line number.
        column: 0-based column offset within the line.
    """

    path: Path
    line: int
    column: int = 0

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A contiguous region of a source file.

    A span is delimited by an inclusive start location and an exclusive end
    location, both within the same file.
    """

    path: Path
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0

    @property
    def is_single_line(self) -> bool:
        """Whether the span begins and ends on the same line."""
        return self.start_line == self.end_line

    @property
    def start(self) -> SourceLocation:
        """The starting location of the span."""
        return SourceLocation(self.path, self.start_line, self.start_column)

    @property
    def end(self) -> SourceLocation:
        """The ending location of the span."""
        return SourceLocation(self.path, self.end_line, self.end_column)

    def __str__(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"
