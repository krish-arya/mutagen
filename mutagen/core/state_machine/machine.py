"""Finite state machine governing run lifecycle transitions.

The transition table is data, not logic, keeping this module free of business
behavior while still enforcing the legal lifecycle.
"""

from __future__ import annotations

from mutagen.core.exceptions import StateTransitionError
from mutagen.core.state_machine.states import RunState

# Legal forward transitions. Every non-terminal state may also transition to
# FAILED or CANCELLED; those edges are added programmatically below.
_BASE_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.INITIALIZING}),
    RunState.INITIALIZING: frozenset({RunState.INGESTING}),
    RunState.INGESTING: frozenset({RunState.SELECTING_TARGETS}),
    RunState.SELECTING_TARGETS: frozenset({RunState.GENERATING_TESTS}),
    RunState.GENERATING_TESTS: frozenset({RunState.GATING}),
    RunState.GATING: frozenset({RunState.REPORTING}),
    RunState.REPORTING: frozenset({RunState.COMPLETED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


def _build_transition_table() -> dict[RunState, frozenset[RunState]]:
    """Augment the base table with universal FAILED/CANCELLED edges."""
    table: dict[RunState, frozenset[RunState]] = {}
    interrupts = frozenset({RunState.FAILED, RunState.CANCELLED})
    for state, allowed in _BASE_TRANSITIONS.items():
        if state.is_terminal:
            table[state] = allowed
        else:
            table[state] = allowed | interrupts
    return table


_TRANSITIONS = _build_transition_table()


class RunStateMachine:
    """Tracks and validates the state of a single run.

    The machine starts in :attr:`RunState.PENDING` and exposes a guarded
    :meth:`transition_to` that rejects illegal moves.
    """

    def __init__(self, *, initial: RunState = RunState.PENDING) -> None:
        self._state = initial

    @property
    def state(self) -> RunState:
        """The current run state."""
        return self._state

    def can_transition(self, target: RunState) -> bool:
        """Whether a move from the current state to ``target`` is legal."""
        return target in _TRANSITIONS[self._state]

    def transition_to(self, target: RunState) -> RunState:
        """Move to ``target`` if legal, returning the new state.

        Raises:
            StateTransitionError: If the transition is not permitted.
        """
        if not self.can_transition(target):
            raise StateTransitionError(
                f"Illegal transition: {self._state.value} -> {target.value}"
            )
        self._state = target
        return self._state
