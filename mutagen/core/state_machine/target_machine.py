"""Finite state machine governing a single target's lifecycle.

Mirrors :class:`mutagen.core.state_machine.machine.RunStateMachine` in shape —
a data-driven transition table guarding illegal moves — but for the per-target
:class:`TargetState` lifecycle. ``DISCARDED`` is reachable from any active
phase (a target can be abandoned at generation, run, or gating); ``KEPT`` is
only reachable once the target has been mutation-gated.
"""

from __future__ import annotations

from mutagen.core.exceptions import StateTransitionError
from mutagen.core.state_machine.target_states import TargetState

# Legal forward transitions. Every active (non-terminal) state may also
# transition to DISCARDED; those edges are added programmatically below.
_BASE_TRANSITIONS: dict[TargetState, frozenset[TargetState]] = {
    TargetState.SELECTED: frozenset({TargetState.GENERATED}),
    TargetState.GENERATED: frozenset({TargetState.RAN}),
    TargetState.RAN: frozenset({TargetState.MUTATED}),
    TargetState.MUTATED: frozenset({TargetState.KEPT}),
    TargetState.KEPT: frozenset(),
    TargetState.DISCARDED: frozenset(),
}


def _build_transition_table() -> dict[TargetState, frozenset[TargetState]]:
    """Augment the base table with the universal DISCARDED edge."""
    table: dict[TargetState, frozenset[TargetState]] = {}
    for state, allowed in _BASE_TRANSITIONS.items():
        if state.is_terminal:
            table[state] = allowed
        else:
            table[state] = allowed | frozenset({TargetState.DISCARDED})
    return table


_TRANSITIONS = _build_transition_table()


class TargetStateMachine:
    """Tracks and validates the state of a single target.

    Starts in :attr:`TargetState.SELECTED` and exposes a guarded
    :meth:`transition_to` that rejects illegal moves.
    """

    def __init__(self, *, initial: TargetState = TargetState.SELECTED) -> None:
        self._state = initial

    @property
    def state(self) -> TargetState:
        """The current target state."""
        return self._state

    def can_transition(self, target: TargetState) -> bool:
        """Whether a move from the current state to ``target`` is legal."""
        return target in _TRANSITIONS[self._state]

    def transition_to(self, target: TargetState) -> TargetState:
        """Move to ``target`` if legal, returning the new state.

        Raises:
            StateTransitionError: If the transition is not permitted.
        """
        if not self.can_transition(target):
            raise StateTransitionError(
                f"Illegal target transition: {self._state.value} -> "
                f"{target.value}"
            )
        self._state = target
        return self._state
