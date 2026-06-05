"""Run state machine.

Models the lifecycle of a mutation-testing run as an explicit finite state
machine, making illegal transitions impossible to perform silently.
"""

from mutagen.core.state_machine.states import RunState
from mutagen.core.state_machine.machine import RunStateMachine

__all__ = ["RunState", "RunStateMachine"]
