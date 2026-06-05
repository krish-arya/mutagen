"""Test-generator port.

A :class:`TestGenerator` synthesizes one or more :class:`GeneratedTest`
artifacts for a given :class:`Target`, typically by prompting an
:class:`LLMClient`. It is pure generation: validation of the tests happens
downstream in the sandbox runner and mutation gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.generation import GenerationInputs
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target


class TestGenerator(ABC):
    """Port for synthesizing candidate tests for a target."""

    @abstractmethod
    async def generate(
        self,
        target: Target,
        context: RepoContext,
        inputs: GenerationInputs | None = None,
    ) -> Sequence[GeneratedTest]:
        """Generate candidate tests for ``target``.

        Args:
            target: The unit of code to generate tests for.
            context: The repository snapshot, providing import roots and
                surrounding source needed to produce importable tests.
            inputs: Optional steering signals — existing test style examples
                and feedback from a prior attempt. When ``None``, generation
                proceeds from the target and context alone.

        Returns:
            A sequence of :class:`GeneratedTest` artifacts; may be empty if no
            test could be produced. Returned tests carry an ``is_valid`` flag —
            an invalid test is still returned (with ``validation_error`` set)
            so the failure is visible to downstream repair.

        Raises:
            TestGenerationError: If generation fails irrecoverably (e.g. the
                LLM call errors).
        """
        raise NotImplementedError
