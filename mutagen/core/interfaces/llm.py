"""LLM client port.

The :class:`TestGenerator` and other stages prompt a language model through
this provider-agnostic port. Concrete adapters live in
``mutagen.infrastructure.llm`` and are responsible for translating to and from
the provider's wire format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.cost import CostInfo


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A normalized response from an LLM provider.

    Attributes:
        text: The model's textual completion.
        model: Identifier of the model that produced the response.
        cost: Token/currency cost attributed to this single call.
        stop_reason: Why generation stopped (e.g. ``"end_turn"``,
            ``"max_tokens"``, ``"refusal"``); empty if unknown.
        metadata: Provider-specific extra fields (request id, etc.).
    """

    text: str
    model: str
    cost: CostInfo = field(default_factory=CostInfo.zero)
    stop_reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_refusal(self) -> bool:
        """Whether the model refused to answer for safety reasons."""
        return self.stop_reason == "refusal"

    @property
    def is_truncated(self) -> bool:
        """Whether generation stopped because it hit the output cap."""
        return self.stop_reason == "max_tokens"

    def validate(self) -> None:
        """Validate the response's invariants.

        Raises:
            ValidationError: If the model id is blank or the cost is invalid.
        """
        if not self.model.strip():
            raise ValidationError("LLMResponse.model must be non-empty.")
        self.cost.validate()


class LLMClient(ABC):
    """Port for issuing completion requests to a language model.

    Implementations are the *only* place in the system permitted to talk to a
    model provider; every other layer depends on this abstraction. Note the
    absence of a ``temperature`` parameter — the target models (Opus 4.7+)
    reject sampling parameters, so behavior is steered by prompting and the
    adapter's configured effort level instead.
    """

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a free-form text completion for ``prompt``.

        Args:
            prompt: The user prompt to complete.
            system: Optional system instruction.
            max_tokens: Optional override for the output-token cap.

        Returns:
            A normalized, validated :class:`LLMResponse`.

        Raises:
            LLMError: If the request fails or the response is unusable.
        """
        raise NotImplementedError

    @abstractmethod
    async def complete_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a completion constrained to a JSON ``schema``.

        The returned response's :attr:`LLMResponse.text` is a JSON document
        conforming to ``schema``. Implementations should request structured
        output from the provider so the result is machine-parseable.

        Args:
            prompt: The user prompt to complete.
            schema: A JSON Schema (draft 2020-12 subset) the output must match.
            system: Optional system instruction.
            max_tokens: Optional override for the output-token cap.

        Returns:
            A normalized, validated :class:`LLMResponse` whose ``text`` is JSON.

        Raises:
            LLMError: If the request fails or the response is unusable.
        """
        raise NotImplementedError
