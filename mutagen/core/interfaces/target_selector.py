"""Target-selector port.

A :class:`TargetSelector` reads a :class:`RepoContext` and chooses, ranks, and
returns the :class:`Target` units worth generating tests for. Selection policy
(coverage gaps, complexity, churn) is an implementation concern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target


class TargetSelector(ABC):
    """Port for selecting and prioritizing test-generation targets."""

    @abstractmethod
    async def select(self, context: RepoContext) -> Sequence[Target]:
        """Select targets from ``context``, ordered by descending priority.

        Args:
            context: The ingested repository snapshot to select from.

        Returns:
            A sequence of validated :class:`Target` objects. May be empty if
            nothing qualifies. Ordering is by descending
            :attr:`Target.priority`.
        """
        raise NotImplementedError
