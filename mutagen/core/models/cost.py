"""Cost-accounting domain model.

:class:`CostInfo` tracks the resource cost of an operation — primarily LLM
token usage and its monetary equivalent — so that generation, selection, and
whole runs can be budgeted and reported.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class CostInfo:
    """Resource cost attributed to an operation.

    All fields are additive, allowing costs from many operations to be summed
    into a run total via :meth:`combine`. The instance is immutable; summation
    returns a new instance.

    Attributes:
        input_tokens: Prompt tokens consumed by the LLM.
        output_tokens: Completion tokens produced by the LLM.
        usd: Monetary cost in US dollars attributed to the operation.
        requests: Number of provider requests made.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    requests: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of input and output tokens."""
        return self.input_tokens + self.output_tokens

    def combine(self, other: CostInfo) -> CostInfo:
        """Return a new :class:`CostInfo` summing ``self`` and ``other``."""
        return CostInfo(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            usd=self.usd + other.usd,
            requests=self.requests + other.requests,
        )

    def validate(self) -> None:
        """Validate that no cost component is negative.

        Raises:
            ValidationError: If any token count, dollar amount, or request
                count is negative.
        """
        for name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("usd", self.usd),
            ("requests", self.requests),
        ):
            if value < 0:
                raise ValidationError(
                    f"CostInfo.{name} must be non-negative, got {value}."
                )

    @classmethod
    def zero(cls) -> CostInfo:
        """Return the additive-identity cost (all components zero)."""
        return cls()
