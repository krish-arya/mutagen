"""Sandbox-runner port.

A :class:`SandboxRunner` executes generated tests in an isolated environment —
optionally against a mutated copy of the source — and reports whether they
pass. Isolation prevents generated or mutated code from affecting the host or
concurrent runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.test_run import SandboxResult


class SandboxRunner(ABC):
    """Port for executing generated tests in an isolated sandbox."""

    @abstractmethod
    async def run(
        self,
        context: RepoContext,
        tests: Sequence[GeneratedTest],
        *,
        mutant_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SandboxResult:
        """Run ``tests`` in isolation and report the outcome.

        Args:
            context: The repository snapshot to materialize in the sandbox.
            tests: Generated tests to write into the sandbox and execute.
            mutant_id: When provided, the sandbox applies the identified mutant
                before running, so the caller can determine if the tests kill
                it. When ``None``, runs against pristine source.
            timeout_seconds: Optional hard timeout for the test execution.

        Returns:
            A :class:`SandboxResult` describing pass/fail and timing.

        Raises:
            SandboxError: If the sandbox cannot be provisioned or torn down.
        """
        raise NotImplementedError
