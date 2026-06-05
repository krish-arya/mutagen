"""Sandbox execution port.

Mutants must be evaluated in isolation so that a mutated codebase cannot
corrupt the host environment or other concurrent evaluations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from mutagen.core.models.mutant import Mutant


@dataclass(frozen=True, slots=True)
class SandboxContext:
    """A prepared, isolated workspace for evaluating a mutant.

    Attributes:
        root: Path to the isolated copy of the project.
        mutant: The mutant applied within this sandbox.
    """

    root: Path
    mutant: Mutant


class Sandbox(ABC):
    """Port for provisioning isolated mutant-evaluation environments."""

    @abstractmethod
    def provision(
        self,
        mutant: Mutant,
    ) -> AbstractAsyncContextManager[SandboxContext]:
        """Provision an isolated environment with ``mutant`` applied.

        The returned async context manager yields a :class:`SandboxContext`
        and is responsible for tearing the environment down on exit.
        """
        raise NotImplementedError
