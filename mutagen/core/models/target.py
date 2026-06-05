"""Target domain model.

A :class:`Target` is a single unit of code selected for test generation —
typically a function, method, or class. Selection is performed by a
:class:`mutagen.core.interfaces.TargetSelector` against a
:class:`mutagen.core.models.repo.RepoContext`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.location import SourceSpan


class TargetKind(str, Enum):
    """The syntactic kind of a selected target."""

    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    MODULE = "module"


@dataclass(frozen=True, slots=True)
class Target:
    """A unit of source code selected for test generation.

    A target binds a fully-qualified symbol to the exact source region that
    defines it, plus the signals the selector used to prioritize it. It is the
    primary input to a :class:`mutagen.core.interfaces.TestGenerator`.

    Attributes:
        target_id: Stable, content-derived identifier, unique within a run.
            Used to correlate generated tests, outcomes, and reports.
        qualified_name: Dotted path to the symbol (e.g.
            ``pkg.module.Class.method``).
        kind: The syntactic kind of the target.
        span: The source region defining the target.
        priority: Selector-assigned score in ``[0.0, 1.0]``; higher means more
            important to cover. Defaults to ``0.0`` (unranked).
        signature: Optional human-readable signature for prompting/reporting.
    """

    target_id: str
    qualified_name: str
    kind: TargetKind
    span: SourceSpan
    priority: float = 0.0
    signature: str = ""

    def validate(self) -> None:
        """Validate the target's invariants.

        Raises:
            ValidationError: If the id or qualified name is blank, the priority
                is outside ``[0.0, 1.0]``, or the span is degenerate
                (end before start).
        """
        if not self.target_id.strip():
            raise ValidationError("Target.target_id must be non-empty.")
        if not self.qualified_name.strip():
            raise ValidationError("Target.qualified_name must be non-empty.")
        if not 0.0 <= self.priority <= 1.0:
            raise ValidationError(
                f"Target.priority must be in [0.0, 1.0], got {self.priority}."
            )
        if self.span.end_line < self.span.start_line:
            raise ValidationError(
                "Target.span end_line precedes start_line "
                f"({self.span.start_line} > {self.span.end_line})."
            )
