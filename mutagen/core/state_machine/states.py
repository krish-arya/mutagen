"""Run lifecycle states."""

from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    """The phases of a mutation-testing run.

    The ordering of members reflects the nominal forward progression of a
    run, though the legal transitions are defined explicitly by the state
    machine rather than implied by this order.
    """

    PENDING = "pending"
    INITIALIZING = "initializing"
    COLLECTING_COVERAGE = "collecting_coverage"
    GENERATING_MUTANTS = "generating_mutants"
    EVALUATING = "evaluating"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Whether no further transitions are permitted from this state."""
        return self in _TERMINAL_STATES


_TERMINAL_STATES: frozenset[RunState] = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
)
