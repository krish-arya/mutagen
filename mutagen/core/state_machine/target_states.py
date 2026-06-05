"""Per-target lifecycle states.

Distinct from :class:`mutagen.core.state_machine.states.RunState` (which models
the *run* lifecycle), :class:`TargetState` models the lifecycle of a single
target as the orchestrator drives it: it is selected, has tests generated, runs
them, mutation-gates them, and is finally kept or discarded.
"""

from __future__ import annotations

from enum import Enum


class TargetState(str, Enum):
    """The phases a single target passes through.

    Forward progression is ``SELECTED -> GENERATED -> RAN -> MUTATED ->
    {KEPT, DISCARDED}``. ``KEPT`` and ``DISCARDED`` are terminal: a target in
    either state is fully processed and is skipped on resume.
    """

    SELECTED = "selected"
    GENERATED = "generated"
    RAN = "ran"
    MUTATED = "mutated"
    KEPT = "kept"
    DISCARDED = "discarded"

    @property
    def is_terminal(self) -> bool:
        """Whether the target is fully processed (kept or discarded)."""
        return self in _TERMINAL_TARGET_STATES


_TERMINAL_TARGET_STATES: frozenset[TargetState] = frozenset(
    {TargetState.KEPT, TargetState.DISCARDED}
)
