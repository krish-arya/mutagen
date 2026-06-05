"""Tests for the run state machine.

These exercise the one piece of real behavior present in the skeleton: the
transition guard. They serve as a template for layer-specific test modules.
"""

from __future__ import annotations

import pytest

from mutagen.core.exceptions import StateTransitionError
from mutagen.core.state_machine import RunState, RunStateMachine


def test_starts_pending() -> None:
    assert RunStateMachine().state is RunState.PENDING


def test_legal_forward_transition() -> None:
    machine = RunStateMachine()
    assert machine.transition_to(RunState.INITIALIZING) is RunState.INITIALIZING


def test_illegal_transition_raises() -> None:
    machine = RunStateMachine()
    with pytest.raises(StateTransitionError):
        machine.transition_to(RunState.COMPLETED)


def test_terminal_state_is_terminal() -> None:
    assert RunState.COMPLETED.is_terminal
    assert not RunState.GENERATING_TESTS.is_terminal


def test_any_active_state_can_fail() -> None:
    machine = RunStateMachine(initial=RunState.GENERATING_TESTS)
    assert machine.transition_to(RunState.FAILED) is RunState.FAILED
