"""Mutation application service.

Coordinates discovery of mutation targets and generation of mutants via the
:class:`MutationGenerator` port, optionally augmented by LLM proposals.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import LLMClient, MutationGenerator
from mutagen.core.models.mutant import Mutant
from mutagen.core.models.target import MutationTarget


@dataclass(slots=True)
class MutationService:
    """Discovers targets and produces the mutant set for a run."""

    config: RunConfig
    generator: MutationGenerator
    llm_client: LLMClient | None = None

    def discover_targets(self) -> Sequence[MutationTarget]:
        """Parse configured sources and return mutable targets."""
        raise NotImplementedError

    def generate(
        self,
        targets: Sequence[MutationTarget],
    ) -> Sequence[Mutant]:
        """Generate all mutants for ``targets``."""
        raise NotImplementedError
