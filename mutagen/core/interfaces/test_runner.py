"""Test-runner port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from mutagen.core.models.test import TestSuiteResult


class TestRunner(ABC):
    """Port for executing a project's test suite."""

    @abstractmethod
    async def run(
        self,
        project_root: Path,
        *,
        selected_tests: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> TestSuiteResult:
        """Execute the test suite and return its result.

        Args:
            project_root: Root of the (possibly mutated) project copy.
            selected_tests: Optional subset of test node ids to run.
            timeout_seconds: Optional hard timeout for the run.

        Returns:
            A :class:`TestSuiteResult` describing the outcomes.
        """
        raise NotImplementedError
