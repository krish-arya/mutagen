"""LLM infrastructure.

The single layer permitted to talk to a model provider. Everything outside
``mutagen.infrastructure.llm`` depends only on the
:class:`mutagen.core.interfaces.LLMClient` port — never on the ``anthropic``
SDK directly.

Components:

* :class:`AnthropicLLMClient` — the provider adapter (retries, backoff,
  timeout, token/cost tracking, structured outputs).
* :class:`PromptBuilder` — renders the generation/repair/strengthening prompts.
* :class:`ResponseParser` — extracts code/JSON and validates against schemas.
* :class:`CostTracker` — prices and accumulates token usage.
"""

from mutagen.infrastructure.llm.anthropic_client import AnthropicLLMClient
from mutagen.infrastructure.llm.cost_tracker import CostTracker, TokenUsage
from mutagen.infrastructure.llm.prompt_builder import (
    GenerationRequest,
    Prompt,
    PromptBuilder,
    RepairRequest,
    StrengthenRequest,
)
from mutagen.infrastructure.llm.response_parser import (
    ResponseParseError,
    ResponseParser,
)

__all__ = [
    "AnthropicLLMClient",
    "PromptBuilder",
    "Prompt",
    "GenerationRequest",
    "RepairRequest",
    "StrengthenRequest",
    "ResponseParser",
    "ResponseParseError",
    "CostTracker",
    "TokenUsage",
]
