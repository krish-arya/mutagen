"""Tests for the per-target state machine."""

from __future__ import annotations

import pytest

from mutagen.core.exceptions import StateTransitionError
from mutagen.core.state_machine import TargetState, TargetStateMachine


def test_starts_selected() -> None:
    assert TargetStateMachine().state is TargetState.SELECTED


def test_full_forward_path() -> None:
    machine = TargetStateMachine()
    for state in (
        TargetState.GENERATED,
        TargetState.RAN,
        TargetState.MUTATED,
        TargetState.KEPT,
    ):
        machine.transition_to(state)
    assert machine.state is TargetState.KEPT


def test_kept_and_discarded_are_terminal() -> None:
    assert TargetState.KEPT.is_terminal
    assert TargetState.DISCARDED.is_terminal
    assert not TargetState.RAN.is_terminal


@pytest.mark.parametrize(
    "active",
    [TargetState.GENERATED, TargetState.RAN, TargetState.MUTATED],
)
def test_discard_reachable_from_any_active_state(active: TargetState) -> None:
    machine = TargetStateMachine(initial=active)
    assert machine.transition_to(TargetState.DISCARDED) is TargetState.DISCARDED


def test_kept_only_from_mutated() -> None:
    with pytest.raises(StateTransitionError):
        TargetStateMachine(initial=TargetState.SELECTED).transition_to(
            TargetState.KEPT
        )
    machine = TargetStateMachine(initial=TargetState.MUTATED)
    assert machine.transition_to(TargetState.KEPT) is TargetState.KEPT


def test_cannot_skip_states() -> None:
    with pytest.raises(StateTransitionError):
        TargetStateMachine().transition_to(TargetState.RAN)


def test_terminal_states_are_dead_ends() -> None:
    with pytest.raises(StateTransitionError):
        TargetStateMachine(initial=TargetState.KEPT).transition_to(
            TargetState.DISCARDED
        )
