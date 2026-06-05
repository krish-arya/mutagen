"""Subprocess-isolated :class:`SandboxRunner` adapter.

Materializes the repository (optionally with a mutant applied) into a
temporary directory and runs the generated tests in a child process, returning
a normalized :class:`SandboxResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from mutagen.config.run_config import SandboxConfig
from mutagen.core.interfaces import SandboxRunner
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.test_run import SandboxResult


@dataclass(slots=True)
class SubprocessSandboxRunner(SandboxRunner):
    """Runs generated tests in an isolated subprocess sandbox."""

    config: SandboxConfig

    async def run(
        self,
        context: RepoContext,
        tests: Sequence[GeneratedTest],
        *,
        mutant_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SandboxResult:
        raise NotImplementedError
