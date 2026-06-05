"""Token and cost tracking for LLM calls.

:class:`CostTracker` converts raw provider token usage into a priced
:class:`CostInfo` and accumulates a running total across many calls. It is the
single place that knows per-model pricing, so the rest of the LLM layer deals
only in normalized :class:`CostInfo` values.

It is pure (no provider SDK, no I/O) and therefore trivially testable.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from mutagen.config.logging import get_logger
from mutagen.config.run_config import LLMConfig
from mutagen.core.models.cost import CostInfo

_logger = get_logger(__name__)

# Tokens are priced per million.
_TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Raw token counts reported by the provider for one call.

    Attributes:
        input_tokens: Uncached prompt tokens billed at full input price.
        output_tokens: Completion tokens.
        cache_read_tokens: Tokens served from the prompt cache (~0.1x price).
        cache_write_tokens: Tokens written to the prompt cache (~1.25x price).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class CostTracker:
    """Accumulates priced token usage across LLM calls.

    Thread-safe: a lock guards the running total so the tracker can be shared
    across concurrent generation tasks.
    """

    # Cache-pricing multipliers relative to the base input price.
    _CACHE_READ_MULTIPLIER = 0.1
    _CACHE_WRITE_MULTIPLIER = 1.25

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._total = CostInfo.zero()

    @property
    def total(self) -> CostInfo:
        """The accumulated cost across all recorded calls."""
        with self._lock:
            return self._total

    def price(self, usage: TokenUsage) -> CostInfo:
        """Convert raw ``usage`` into a priced :class:`CostInfo` for one call.

        This does not mutate the running total; use :meth:`record` to both
        price and accumulate.

        Args:
            usage: Raw token counts from the provider.

        Returns:
            A :class:`CostInfo` for the single call, including USD.
        """
        input_rate = self._config.input_usd_per_mtok / _TOKENS_PER_MILLION
        output_rate = self._config.output_usd_per_mtok / _TOKENS_PER_MILLION

        usd = (
            usage.input_tokens * input_rate
            + usage.output_tokens * output_rate
            + usage.cache_read_tokens * input_rate * self._CACHE_READ_MULTIPLIER
            + usage.cache_write_tokens
            * input_rate
            * self._CACHE_WRITE_MULTIPLIER
        )
        return CostInfo(
            input_tokens=usage.input_tokens
            + usage.cache_read_tokens
            + usage.cache_write_tokens,
            output_tokens=usage.output_tokens,
            usd=usd,
            requests=1,
        )

    def record(self, usage: TokenUsage) -> CostInfo:
        """Price ``usage``, add it to the running total, and return the delta.

        Args:
            usage: Raw token counts from the provider.

        Returns:
            The priced :class:`CostInfo` for this single call.
        """
        cost = self.price(usage)
        with self._lock:
            self._total = self._total.combine(cost)
        _logger.debug(
            "llm call recorded",
            extra={
                "context": {
                    "input_tokens": cost.input_tokens,
                    "output_tokens": cost.output_tokens,
                    "usd": round(cost.usd, 6),
                }
            },
        )
        return cost

    def reset(self) -> None:
        """Reset the running total to zero."""
        with self._lock:
            self._total = CostInfo.zero()
