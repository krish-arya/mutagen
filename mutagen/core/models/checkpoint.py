"""Checkpoint domain models for resumable runs.

These capture the *progress* of a run — which targets have been processed and
in what state — distinct from the final :class:`mutagen.core.models.run.RunResult`
artifact. A :class:`TargetCheckpoint` is persisted immediately as each target
finishes; a :class:`RunCheckpoint` is the aggregate the orchestrator loads to
resume, skipping targets already in a terminal state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.outcome import TargetOutcome
from mutagen.core.state_machine.target_states import TargetState


@dataclass(frozen=True, slots=True)
class TargetCheckpoint:
    """The persisted progress of a single target.

    Attributes:
        target_id: Identifier of the target.
        state: The target's lifecycle state when this checkpoint was written.
        outcome: The target's outcome, present once it reached a terminal
            state; ``None`` while still in progress.
        attempts: Number of generation attempts spent (initial + repairs +
            strengthenings), for budget accounting and diagnostics.
    """

    target_id: str
    state: TargetState
    outcome: TargetOutcome | None = None
    attempts: int = 0

    @property
    def is_done(self) -> bool:
        """Whether the target reached a terminal state (kept/discarded)."""
        return self.state.is_terminal

    def validate(self) -> None:
        """Validate the checkpoint's invariants.

        Raises:
            ValidationError: If the target id is blank, the attempt count is
                negative, a terminal checkpoint lacks an outcome, or the nested
                outcome is invalid.
        """
        if not self.target_id.strip():
            raise ValidationError("TargetCheckpoint.target_id must be non-empty.")
        if self.attempts < 0:
            raise ValidationError(
                "TargetCheckpoint.attempts must be non-negative."
            )
        if self.state.is_terminal and self.outcome is None:
            raise ValidationError(
                "A terminal TargetCheckpoint must carry an outcome."
            )
        if self.outcome is not None:
            self.outcome.validate()


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    """The persisted progress of a whole run, for resume.

    Attributes:
        run_id: Identifier of the run.
        targets: Per-target checkpoints, keyed by target id.
        cost: Total cost accumulated so far across the run.
        started_at: Unix epoch seconds when the run began.
    """

    run_id: str
    targets: dict[str, TargetCheckpoint] = field(default_factory=dict)
    cost: CostInfo = field(default_factory=CostInfo.zero)
    started_at: float = 0.0

    def is_target_done(self, target_id: str) -> bool:
        """Whether ``target_id`` is recorded as terminally processed."""
        checkpoint = self.targets.get(target_id)
        return checkpoint is not None and checkpoint.is_done

    @property
    def completed_outcomes(self) -> tuple[TargetOutcome, ...]:
        """Outcomes of all targets that reached a terminal state."""
        return tuple(
            cp.outcome
            for cp in self.targets.values()
            if cp.outcome is not None
        )

    def validate(self) -> None:
        """Validate the run checkpoint and all nested target checkpoints.

        Raises:
            ValidationError: If the run id is blank, or any nested cost or
                target checkpoint is invalid.
        """
        if not self.run_id.strip():
            raise ValidationError("RunCheckpoint.run_id must be non-empty.")
        self.cost.validate()
        for checkpoint in self.targets.values():
            checkpoint.validate()
