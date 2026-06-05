"""Anthropic-backed :class:`LLMClient` adapter.

Wraps the Anthropic Messages API to provide LLM-assisted mutation proposals.
Concrete request/response handling is deferred.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import LLMConfig
from mutagen.core.interfaces import LLMClient, LLMResponse


@dataclass(slots=True)
class AnthropicLLMClient(LLMClient):
    """:class:`LLMClient` implementation backed by the Anthropic API."""

    config: LLMConfig

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
