"""Generation-input value object.

:class:`GenerationInputs` carries the optional, caller-supplied signals that
shape test generation beyond the target itself: examples of the project's
existing test style (so generated tests match house conventions) and free-form
feedback from a previous attempt (so generation can be steered or retried).

It is a pure value object in the domain layer so the
:class:`mutagen.core.interfaces.TestGenerator` port can reference it without
depending on any infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GenerationInputs:
    """Optional steering inputs for a generation request.

    Attributes:
        style_examples: Source snippets of existing tests in the project,
            included verbatim so the model matches local conventions.
        feedback: Free-form guidance from a prior attempt (e.g. a reviewer
            note, or a summary of why the last generation was unsatisfactory).
    """

    style_examples: tuple[str, ...] = field(default_factory=tuple)
    feedback: str = ""

    @property
    def has_examples(self) -> bool:
        """Whether any style examples were supplied."""
        return bool(self.style_examples)

    @property
    def has_feedback(self) -> bool:
        """Whether feedback was supplied."""
        return bool(self.feedback.strip())
