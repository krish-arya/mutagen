"""Built-in mutation operators.

Each operator implements :class:`MutationOperator` for one syntactic category.
Transformation logic is deferred; only the contracts are declared here.
"""

from __future__ import annotations

from collections.abc import Iterable

from mutagen.core.interfaces import MutationOperator
from mutagen.core.models.mutant import Mutant
from mutagen.core.models.target import MutationTarget


class ArithmeticOperator(MutationOperator):
    """Swaps binary arithmetic operators (e.g. ``+`` to ``-``)."""

    @property
    def name(self) -> str:
        return "arithmetic"

    def applies_to(self, target: MutationTarget) -> bool:
        raise NotImplementedError

    def generate(self, target: MutationTarget) -> Iterable[Mutant]:
        raise NotImplementedError


class ComparisonOperator(MutationOperator):
    """Swaps comparison operators (e.g. ``<`` to ``<=``)."""

    @property
    def name(self) -> str:
        return "comparison"

    def applies_to(self, target: MutationTarget) -> bool:
        raise NotImplementedError

    def generate(self, target: MutationTarget) -> Iterable[Mutant]:
        raise NotImplementedError
