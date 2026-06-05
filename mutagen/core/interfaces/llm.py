"""LLM client port.

Mutagen can use a large language model to propose semantically meaningful
mutations. The contract here is provider-agnostic; concrete adapters live in
``mutagen.infrastructure.llm``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A normalized response from an LLM provider.

    Attributes:
        text: The model's textual completion.
        model: Identifier of the model that produced the response.
        input_tokens: Tokens consumed by the prompt.
        output_tokens: Tokens produced in the completion.
        metadata: Provider-specific extra fields.
    """

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


class LLMClient(ABC):
    """Port for issuing completion requests to a language model."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Generate a completion for ``prompt``.

        Args:
            prompt: The user prompt to complete.
            system: Optional system instruction.
            max_tokens: Optional cap on output tokens.
            temperature: Optional sampling temperature.

        Returns:
            A normalized :class:`LLMResponse`.
        """
        raise NotImplementedError
