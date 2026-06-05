"""Anthropic-backed :class:`LLMClient` adapter.

This is the **only** module in the system that talks to the Anthropic API. The
``anthropic`` SDK is imported lazily inside the methods that need it, so the
rest of the LLM layer (prompt building, parsing, cost tracking) imports and
tests cleanly without the SDK installed.

Production concerns handled here:

* **Adaptive thinking + effort** — targets Opus 4.7+; no sampling parameters
  (``temperature``/``top_p``) are ever sent, since those models reject them.
* **Timeouts** — a per-request timeout from config, applied via the SDK.
* **Retries with exponential backoff** — the SDK retries 429/5xx on its own;
  this adapter adds an outer backoff loop for resilience and structured
  logging of each attempt.
* **Token & cost tracking** — usage from every response is fed to a shared
  :class:`CostTracker` and attached to the returned :class:`LLMResponse`.
* **Structured outputs** — ``complete_structured`` constrains the response to
  a JSON Schema via ``output_config.format``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.config.run_config import LLMConfig
from mutagen.core.exceptions import LLMError
from mutagen.core.interfaces import LLMClient, LLMResponse
from mutagen.infrastructure.llm.cost_tracker import CostTracker, TokenUsage

_logger = get_logger(__name__)


class AnthropicLLMClient(LLMClient):
    """:class:`LLMClient` implementation backed by the Anthropic API.

    Args:
        config: LLM configuration (model, effort, timeout, retries, pricing).
        client: An ``AsyncAnthropic``-compatible client. Injected for tests;
            when ``None`` a real client is constructed lazily on first use.
        cost_tracker: Shared cost accumulator; created from ``config`` when not
            supplied.
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        client: Any | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._cost_tracker = cost_tracker or CostTracker(config)

    @property
    def cost_tracker(self) -> CostTracker:
        """The cost tracker accumulating usage across calls."""
        return self._cost_tracker

    # ------------------------------------------------------------------ #
    # Public port methods
    # ------------------------------------------------------------------ #

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a free-form completion. See :meth:`LLMClient.complete`."""
        params = self._base_params(prompt, system, max_tokens)
        message = await self._send(params)
        return self._to_response(message)

    async def complete_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate JSON-constrained output. See the port for the contract."""
        params = self._base_params(prompt, system, max_tokens)
        params["output_config"] = {
            **params.get("output_config", {}),
            "format": {"type": "json_schema", "schema": schema},
        }
        message = await self._send(params)
        return self._to_response(message)

    # ------------------------------------------------------------------ #
    # Request construction
    # ------------------------------------------------------------------ #

    def _base_params(
        self, prompt: str, system: str | None, max_tokens: int | None
    ) -> dict[str, Any]:
        """Build the common Messages API parameters from config.

        Uses adaptive thinking and the configured effort level; never sends
        ``temperature``/``top_p``/``top_k`` (rejected by Opus 4.7+).
        """
        output_config: dict[str, Any] = {"effort": self._config.effort.value}
        params: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": max_tokens or self._config.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": output_config,
        }
        if self._config.adaptive_thinking:
            params["thinking"] = {"type": "adaptive"}
        if system is not None:
            params["system"] = system
        return params

    # ------------------------------------------------------------------ #
    # Transport: retries, timeout, backoff
    # ------------------------------------------------------------------ #

    async def _send(self, params: dict[str, Any]) -> Any:
        """Send a request with timeout and exponential-backoff retries.

        The SDK already retries 429/5xx internally; this outer loop adds a
        bounded backoff and structured per-attempt logging, and re-raises
        non-retryable errors immediately.

        Raises:
            LLMError: If all attempts fail.
        """
        client = self._ensure_client()
        attempts = self._config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await client.messages.create(**params)
            except Exception as exc:  # noqa: BLE001 - normalized below
                last_error = exc
                if not self._is_retryable(exc) or attempt == attempts:
                    raise self._normalize_error(exc) from exc
                delay = self._config.retry_backoff_seconds * (2 ** (attempt - 1))
                _logger.warning(
                    "llm request failed; retrying",
                    extra={
                        "context": {
                            "attempt": attempt,
                            "max_attempts": attempts,
                            "delay_seconds": delay,
                            "error": type(exc).__name__,
                        }
                    },
                )
                await asyncio.sleep(delay)

        # Unreachable: the loop either returns or raises.
        raise self._normalize_error(last_error)  # pragma: no cover

    def _ensure_client(self) -> Any:
        """Return the injected client, or lazily construct a real one."""
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise LLMError(
                "The 'anthropic' package is required to call the LLM."
            ) from exc
        self._client = anthropic.AsyncAnthropic(
            timeout=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
        )
        return self._client

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Whether ``exc`` represents a transient, retryable failure."""
        try:
            import anthropic
        except ImportError:  # pragma: no cover - optional dependency
            return False
        retryable = (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )
        if isinstance(exc, retryable):
            return True
        status = getattr(exc, "status_code", None)
        return isinstance(status, int) and status >= 500

    @staticmethod
    def _normalize_error(exc: Exception | None) -> LLMError:
        """Wrap a provider/transport error as a domain :class:`LLMError`."""
        if isinstance(exc, LLMError):
            return exc
        return LLMError(f"LLM request failed: {exc}")

    # ------------------------------------------------------------------ #
    # Response normalization
    # ------------------------------------------------------------------ #

    def _to_response(self, message: Any) -> LLMResponse:
        """Normalize a provider message into a validated :class:`LLMResponse`."""
        text = self._extract_text(message)
        usage = self._extract_usage(message)
        cost = self._cost_tracker.record(usage)

        metadata: dict[str, str] = {}
        request_id = getattr(message, "_request_id", None)
        if request_id:
            metadata["request_id"] = str(request_id)

        response = LLMResponse(
            text=text,
            model=str(getattr(message, "model", self._config.model)),
            cost=cost,
            stop_reason=str(getattr(message, "stop_reason", "") or ""),
            metadata=metadata,
        )
        response.validate()
        return response

    @staticmethod
    def _extract_text(message: Any) -> str:
        """Concatenate the text blocks of a provider message."""
        parts: list[str] = []
        for block in getattr(message, "content", []) or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "".join(parts)

    @staticmethod
    def _extract_usage(message: Any) -> TokenUsage:
        """Pull token counts from a provider message's ``usage`` block."""
        usage = getattr(message, "usage", None)
        if usage is None:
            return TokenUsage()
        return TokenUsage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
