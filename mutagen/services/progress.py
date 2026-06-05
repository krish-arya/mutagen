"""Progress reporting for a run.

A light, dependency-free event channel the orchestrator uses to announce
progress without knowing how it is displayed. The CLI subscribes with a Rich
live progress bar; tests subscribe with a list recorder; a ``None`` listener
disables reporting entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ProgressPhase(str, Enum):
    """Coarse phases announced during a run."""

    INGESTING = "ingesting"
    SELECTING = "selecting"
    PROCESSING = "processing"
    REPORTING = "reporting"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """A single progress announcement.

    Attributes:
        phase: The phase the run is in.
        message: Human-readable status line.
        completed: Targets completed so far (during PROCESSING).
        total: Total targets to process (during PROCESSING), or ``None`` when
            not yet known.
    """

    phase: ProgressPhase
    message: str = ""
    completed: int = 0
    total: int | None = None


class ProgressListener(Protocol):
    """Receives :class:`ProgressEvent`s as a run proceeds."""

    def __call__(self, event: ProgressEvent) -> None: ...
