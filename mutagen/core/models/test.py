"""Test-execution domain models.

These types describe the test suite and the results of running it, decoupled
from any particular test runner (pytest, unittest, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TestOutcome(str, Enum):
    """Outcome of an individual test case."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class TestCase:
    """A single test identified within the suite.

    Attributes:
        node_id: Runner-specific identifier (e.g. pytest node id).
        name: Short, human-readable test name.
    """

    node_id: str
    name: str


@dataclass(frozen=True, slots=True)
class TestSuiteResult:
    """Aggregate result of executing the test suite.

    Attributes:
        outcomes: Mapping of test node id to its outcome.
        duration_seconds: Total wall-clock execution time.
        exit_code: Raw exit code from the underlying runner.
    """

    outcomes: dict[str, TestOutcome] = field(default_factory=dict)
    duration_seconds: float = 0.0
    exit_code: int = 0

    @property
    def passed(self) -> bool:
        """Whether every test passed."""
        return all(o is TestOutcome.PASSED for o in self.outcomes.values())

    @property
    def failing_tests(self) -> tuple[str, ...]:
        """Node ids of tests that failed or errored."""
        return tuple(
            node_id
            for node_id, outcome in self.outcomes.items()
            if outcome in (TestOutcome.FAILED, TestOutcome.ERROR)
        )
