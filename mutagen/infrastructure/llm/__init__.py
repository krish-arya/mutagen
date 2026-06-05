"""LLM adapters implementing :class:`mutagen.core.interfaces.LLMClient`."""

from mutagen.infrastructure.llm.anthropic_client import AnthropicLLMClient

__all__ = ["AnthropicLLMClient"]
