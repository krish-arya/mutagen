"""Parsing and validation of LLM responses.

:class:`ResponseParser` turns a raw :class:`LLMResponse` into the concrete
artifact a stage needs — a Python source string, or a JSON object validated
against a schema. It also normalizes the common ways models wrap output
(Markdown code fences) and surfaces refusals/truncation as typed errors.

JSON validation uses the optional ``jsonschema`` dependency; it is imported
lazily so the rest of the LLM layer works without it installed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.core.exceptions import LLMError
from mutagen.core.interfaces import LLMResponse

_logger = get_logger(__name__)

# Matches a fenced code block, optionally tagged (```python ... ``` / ``` ... ```).
_FENCE_RE = re.compile(
    r"```(?:[a-zA-Z0-9_+-]*)\n(?P<body>.*?)```",
    re.DOTALL,
)


class ResponseParseError(LLMError):
    """Raised when a response cannot be parsed into the expected shape."""


class ResponseParser:
    """Extracts and validates structured artifacts from LLM responses."""

    def extract_code(self, response: LLMResponse) -> str:
        """Return the Python source carried by ``response``.

        Strips a single surrounding Markdown fence if present; otherwise
        returns the trimmed text as-is (the generation prompt asks for raw
        source, but models sometimes fence anyway).

        Args:
            response: The response to extract from.

        Returns:
            The extracted source code.

        Raises:
            ResponseParseError: If the response was a refusal or is empty.
        """
        self._guard(response)
        text = response.text.strip()
        match = _FENCE_RE.search(text)
        code = match.group("body") if match else text
        code = code.strip()
        if not code:
            raise ResponseParseError("Response contained no usable code.")
        return code

    def parse_json(
        self,
        response: LLMResponse,
        schema: dict[str, Any] | None = None,
    ) -> Any:
        """Parse ``response`` text as JSON, optionally validating a schema.

        Args:
            response: The response whose text is a JSON document.
            schema: Optional JSON Schema to validate against. When provided
                and ``jsonschema`` is installed, the parsed value is validated.

        Returns:
            The parsed (and, if requested, validated) JSON value.

        Raises:
            ResponseParseError: On refusal, empty output, invalid JSON, or
                schema-validation failure.
        """
        self._guard(response)
        raw = self._strip_fence(response.text.strip())
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ResponseParseError(
                f"Response was not valid JSON: {exc}"
            ) from exc
        if schema is not None:
            self.validate_schema(value, schema)
        return value

    def validate_schema(self, value: Any, schema: dict[str, Any]) -> None:
        """Validate ``value`` against ``schema`` using ``jsonschema``.

        Args:
            value: The parsed JSON value.
            schema: The JSON Schema to validate against.

        Raises:
            ResponseParseError: If validation fails.
            LLMError: If ``jsonschema`` is not installed.
        """
        try:
            import jsonschema
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise LLMError(
                "Schema validation requires the 'jsonschema' package."
            ) from exc

        try:
            jsonschema.validate(instance=value, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ResponseParseError(
                f"Structured output failed schema validation: {exc.message}"
            ) from exc

    @staticmethod
    def _strip_fence(text: str) -> str:
        """Remove a surrounding Markdown fence if one wraps the whole text."""
        match = _FENCE_RE.search(text)
        if match and match.group("body").strip():
            return match.group("body").strip()
        return text

    @staticmethod
    def _guard(response: LLMResponse) -> None:
        """Raise if the response is a refusal or otherwise unusable."""
        if response.is_refusal:
            raise ResponseParseError(
                "Model refused the request; no output to parse."
            )
        if not response.text.strip():
            if response.is_truncated:
                raise ResponseParseError(
                    "Response was empty and truncated (hit max_tokens)."
                )
            raise ResponseParseError("Response was empty.")
