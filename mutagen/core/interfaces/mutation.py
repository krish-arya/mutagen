"""Mutation-generation ports.

An :class:`MutationOperator` knows how to mutate a single kind of construct;
a :class:`MutationGenerator` orchestrates operators across a set of targets.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence

from mutagen.core.models.mutant import Mutant
from mutagen.core.models.target import MutationTarget


class MutationOperator(ABC):
    """Port for a single mutation operator (e.g. arithmetic-operator swap)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable, unique operator name."""
        raise NotImplementedError

    @abstractmethod
    def applies_to(self, target: MutationTarget) -> bool:
        """Whether this operator can mutate ``target``."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, target: MutationTarget) -> Iterable[Mutant]:
        """Yield the mutants this operator produces for ``target``."""
        raise NotImplementedError


class MutationGenerator(ABC):
    """Port for producing the full set of mutants for a run."""

    @abstractmethod
    def generate(self, targets: Sequence[MutationTarget]) -> Sequence[Mutant]:
        """Produce all mutants for the given targets."""
        raise NotImplementedError
