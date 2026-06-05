"""State machines.

Two explicit finite state machines make illegal transitions impossible to
perform silently: :class:`RunStateMachine` models the *run* lifecycle
(ingest → select → generate → gate → report), and :class:`TargetStateMachine`
models a single *target*'s lifecycle (selected → generated → ran → mutated →
kept/discarded).
"""

from mutagen.core.state_machine.machine import RunStateMachine
from mutagen.core.state_machine.states import RunState
from mutagen.core.state_machine.target_machine import TargetStateMachine
from mutagen.core.state_machine.target_states import TargetState

__all__ = [
    "RunState",
    "RunStateMachine",
    "TargetState",
    "TargetStateMachine",
]
