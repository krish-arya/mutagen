"""AST-based :class:`MutationGenerator` adapter.

Walks the Python AST of each target module to enumerate mutable nodes and
dispatches them through the registered operators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence

from mutagen.core.interfaces import MutationGenerator, MutationOperator
from mutagen.core.models.mutant import Mutant
from mutagen.core.models.target import MutationTarget


@dataclass(slots=True)
class AstMutationGenerator(MutationGenerator):
    """Generates mutants by applying operators across AST targets."""

    operators: tuple[MutationOperator, ...] = field(default_factory=tuple)

    def generate(self, targets: Sequence[MutationTarget]) -> Sequence[Mutant]:
        raise NotImplementedError
