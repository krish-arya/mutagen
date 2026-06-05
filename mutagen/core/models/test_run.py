"""Sandbox test-run result model.

:class:`SandboxResult` is the normalized outcome of executing a set of
generated tests inside a sandbox, decoupled from any specific test runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mutagen.core.exceptions import ValidationError


class RunnerStatus(str, Enum):
    """Outcome of a sandbox test execution."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Normalized result of running generated tests in a sandbox.

    Attributes:
        status: Overall execution status.
        passed_test_ids: Ids of generated tests that passed.
        failed_test_ids: Ids of generated tests that failed or errored.
        flaky_test_ids: Ids of tests whose verdict differed across repeated
            runs (non-deterministic). A non-empty set drives the overall
            status to :attr:`RunnerStatus.ERROR`, since a flaky suite cannot
            reliably gate mutants.
        duration_seconds: Wall-clock execution time.
        exit_code: Raw exit code from the underlying runner.
        output: Captured stdout/stderr, truncated by the adapter as needed.
    """

    status: RunnerStatus
    passed_test_ids: tuple[str, ...] = field(default_factory=tuple)
    failed_test_ids: tuple[str, ...] = field(default_factory=tuple)
    flaky_test_ids: tuple[str, ...] = field(default_factory=tuple)
    duration_seconds: float = 0.0
    exit_code: int = 0
    output: str = ""

    @property
    def passed(self) -> bool:
        """Whether the execution completed with all tests passing."""
        return self.status is RunnerStatus.PASSED

    @property
    def is_flaky(self) -> bool:
        """Whether any test produced a non-deterministic verdict."""
        return bool(self.flaky_test_ids)

    def validate(self) -> None:
        """Validate the result's invariants.

        Raises:
            ValidationError: If the duration is negative, or a test id appears
                in both the passed and failed sets.
        """
        if self.duration_seconds < 0:
            raise ValidationError(
                "SandboxResult.duration_seconds must be non-negative."
            )
        overlap = set(self.passed_test_ids) & set(self.failed_test_ids)
        if overlap:
            raise ValidationError(
                f"SandboxResult test ids cannot be both passed and failed: "
                f"{sorted(overlap)}."
            )
