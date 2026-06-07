"""OpenAI-compatible :class:`LLMClient` adapter.

A single adapter serving every provider that speaks the OpenAI Chat Completions
API — **OpenAI**, **OpenRouter**, and **Gemini's** OpenAI-compatible endpoint —
differing only by ``base_url``, key, and model. The ``openai`` SDK is imported
lazily so the rest of the LLM layer imports and tests without it installed.

Production concerns handled here mirror the Anthropic adapter:

* **Timeout & retries** — a per-request timeout plus an outer exponential
  backoff loop over transient failures, with structured per-attempt logging.
* **Token & cost tracking** — usage from every response feeds the shared
  :class:`CostTracker`.
* **Optional sampling** — ``temperature`` is sent only when configured (these
  providers accept it, unlike the Anthropic-targeted models).
* **Structured outputs** — ``complete_structured`` requests the provider's
  native ``response_format`` JSON-schema mode, and **falls back** to embedding
  the schema in the prompt for endpoints that don't support it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.config.run_config import LLMConfig
from mutagen.core.exceptions import LLMError
from mutagen.core.interfaces import LLMClient, LLMResponse
from mutagen.infrastructure.llm.cost_tracker import CostTracker, TokenUsage

_logger = get_logger(__name__)


class OpenAICompatLLMClient(LLMClient):
    """:class:`LLMClient` over the OpenAI Chat Completions API.

    Serves OpenAI, OpenRouter, and Gemini (OpenAI-compat) via one code path;
    the provider distinction lives entirely in ``config.base_url``,
    ``config.api_key_env``, and ``config.model``.

    Args:
        config: LLM configuration (provider, model, base_url, temperature, …).
        api_key: The resolved API key. Injected by the container from the
            environment variable named by ``config.api_key_env``.
        client: An ``AsyncOpenAI``-compatible client. Injected for tests; when
            ``None`` a real client is constructed lazily on first use.
        cost_tracker: Shared cost accumulator; created from ``config`` when not
            supplied.
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
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
        """Generate JSON-constrained output, native with a prompt fallback.

        Tries the provider's native ``response_format`` JSON-schema mode; if the
        endpoint rejects it (older/partial OpenAI-compat servers), retries once
        with the schema embedded in the prompt and ``json_object`` mode.
        """
        params = self._base_params(prompt, system, max_tokens)
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": schema, "strict": True},
        }
        try:
            message = await self._send(params)
        except LLMError:
            # Fallback: not all OpenAI-compat servers honour json_schema.
            _logger.warning(
                "native json_schema unsupported; falling back to prompt-embedded "
                "schema",
                extra={"context": {"provider": self._config.provider}},
            )
            fallback = self._base_params(
                self._schema_prompt(prompt, schema), system, max_tokens
            )
            fallback["response_format"] = {"type": "json_object"}
            message = await self._send(fallback)
        return self._to_response(message)

    # ------------------------------------------------------------------ #
    # Request construction
    # ------------------------------------------------------------------ #

    def _base_params(
        self, prompt: str, system: str | None, max_tokens: int | None
    ) -> dict[str, Any]:
        """Build the common Chat Completions parameters from config."""
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        params: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": max_tokens or self._config.max_tokens,
            "messages": messages,
        }
        if self._config.temperature is not None:
            params["temperature"] = self._config.temperature
        return params

    @staticmethod
    def _schema_prompt(prompt: str, schema: dict[str, Any]) -> str:
        """Embed a JSON schema in the prompt for the no-native-schema fallback."""
        return (
            f"{prompt}\n\n"
            "Respond with a single JSON object that conforms exactly to this "
            "JSON Schema. Output only the JSON, with no prose or code fences:\n"
            f"{json.dumps(schema)}"
        )

    # ------------------------------------------------------------------ #
    # Transport: retries, timeout, backoff
    # ------------------------------------------------------------------ #

    async def _send(self, params: dict[str, Any]) -> Any:
        """Send a request with timeout and exponential-backoff retries.

        Raises:
            LLMError: If all attempts fail.
        """
        client = self._ensure_client()
        attempts = self._config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await client.chat.completions.create(**params)
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

        raise self._normalize_error(last_error)  # pragma: no cover

    def _ensure_client(self) -> Any:
        """Return the injected client, or lazily construct a real one."""
        if self._client is not None:
            return self._client
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise LLMError(
                "The 'openai' package is required for the "
                f"'{self._config.provider}' provider. Install it with "
                "pip install 'mutagen-ai[openai]'."
            ) from exc
        if not self._api_key:
            raise LLMError(
                f"No API key found in ${self._config.api_key_env} for provider "
                f"'{self._config.provider}'."
            )
        kwargs: dict[str, Any] = {
            "api_key": self._api_key,
            "timeout": self._config.timeout_seconds,
            "max_retries": self._config.max_retries,
        }
        if self._config.base_url:
            kwargs["base_url"] = self._config.base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Whether ``exc`` represents a transient, retryable failure."""
        try:
            import openai
        except ImportError:  # pragma: no cover - optional dependency
            return False
        retryable = (
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APIConnectionError,
            openai.APITimeoutError,
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
        """Normalize a Chat Completion into a validated :class:`LLMResponse`."""
        text = self._extract_text(message)
        usage = self._extract_usage(message)
        cost = self._cost_tracker.record(usage)

        metadata: dict[str, str] = {}
        request_id = getattr(message, "id", None)
        if request_id:
            metadata["request_id"] = str(request_id)

        response = LLMResponse(
            text=text,
            model=str(getattr(message, "model", self._config.model)),
            cost=cost,
            stop_reason=self._extract_stop_reason(message),
            metadata=metadata,
        )
        response.validate()
        return response

    @staticmethod
    def _extract_text(message: Any) -> str:
        """Pull the assistant text from the first choice."""
        choices = getattr(message, "choices", None) or []
        if not choices:
            return ""
        content = getattr(choices[0].message, "content", None)
        return content or ""

    @staticmethod
    def _extract_stop_reason(message: Any) -> str:
        """Map the OpenAI ``finish_reason`` to the normalized stop reason."""
        choices = getattr(message, "choices", None) or []
        if not choices:
            return ""
        reason = getattr(choices[0], "finish_reason", "") or ""
        # Normalize "length" -> "max_tokens" so LLMResponse.is_truncated works.
        return "max_tokens" if reason == "length" else str(reason)

    @staticmethod
    def _extract_usage(message: Any) -> TokenUsage:
        """Pull token counts from a Chat Completion's ``usage`` block."""
        usage = getattr(message, "usage", None)
        if usage is None:
            return TokenUsage()
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
        return TokenUsage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cache_read_tokens=cached or 0,
            cache_write_tokens=0,
        )
