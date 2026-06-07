"""Tests for the OpenAI-compatible LLM adapter.

All API interaction is mocked: a :class:`FakeAsyncOpenAI` stands in for
``AsyncOpenAI`` and returns scripted :class:`FakeCompletion` objects shaped like
Chat Completions responses. No network calls are made and the real ``openai``
SDK is never invoked. Covers happy path, optional temperature, usage/cost,
finish-reason normalization, the structured-output native + prompt fallback,
and retries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mutagen.config.run_config import LLMConfig
from mutagen.core.exceptions import LLMError
from mutagen.infrastructure.llm import OpenAICompatLLMClient

# --------------------------------------------------------------------------- #
# Mock SDK objects (shaped like the OpenAI Chat Completions response)
# --------------------------------------------------------------------------- #


@dataclass
class FakeMessageObj:
    content: str | None = "ok"


@dataclass
class FakeChoice:
    message: FakeMessageObj = field(default_factory=FakeMessageObj)
    finish_reason: str = "stop"


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens_details: Any = None


@dataclass
class FakeCompletion:
    choices: list[FakeChoice]
    model: str = "openrouter/some-model"
    id: str = "chatcmpl_test_123"
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeCompletions:
    def __init__(self, owner: FakeAsyncOpenAI) -> None:
        self._owner = owner

    async def create(self, **params: Any) -> FakeCompletion:
        self._owner.calls.append(params)
        behavior = self._owner.behaviors.pop(0) if self._owner.behaviors else None
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(params)
        if isinstance(behavior, FakeCompletion):
            return behavior
        return FakeCompletion(choices=[FakeChoice()])


class FakeChat:
    def __init__(self, owner: FakeAsyncOpenAI) -> None:
        self.completions = FakeCompletions(owner)


class FakeAsyncOpenAI:
    """Stand-in for ``AsyncOpenAI`` recording calls and scripting results."""

    def __init__(self, behaviors: list[Any] | None = None) -> None:
        self.behaviors: list[Any] = list(behaviors or [])
        self.calls: list[dict[str, Any]] = []
        self.chat = FakeChat(self)


def _config(**kwargs: Any) -> LLMConfig:
    base: dict[str, Any] = {
        "provider": "openrouter",
        "model": "openrouter/some-model",
        "retry_backoff_seconds": 0.0,
        "input_usd_per_mtok": 0.0,  # free models -> zero cost
        "output_usd_per_mtok": 0.0,
    }
    base.update(kwargs)
    return LLMConfig(**base)


def _completion(text: str = "result", **kwargs: Any) -> FakeCompletion:
    return FakeCompletion(
        choices=[FakeChoice(message=FakeMessageObj(content=text))], **kwargs
    )


# --------------------------------------------------------------------------- #
# Happy path, params, usage
# --------------------------------------------------------------------------- #


async def test_complete_returns_text_and_tracks_cost() -> None:
    client = FakeAsyncOpenAI(
        behaviors=[
            _completion(
                "generated tests",
                usage=FakeUsage(prompt_tokens=1000, completion_tokens=500),
            )
        ]
    )
    llm = OpenAICompatLLMClient(_config(), api_key="sk-x", client=client)

    response = await llm.complete("write tests", system="be terse")

    assert response.text == "generated tests"
    assert response.stop_reason == "stop"
    assert response.cost.input_tokens == 1000
    assert response.cost.output_tokens == 500
    assert response.metadata["request_id"] == "chatcmpl_test_123"
    assert llm.cost_tracker.total.requests == 1


async def test_system_prepended_as_message() -> None:
    client = FakeAsyncOpenAI(behaviors=[_completion()])
    llm = OpenAICompatLLMClient(_config(), api_key="sk-x", client=client)

    await llm.complete("hello", system="sys", max_tokens=2048)

    params = client.calls[0]
    assert params["max_tokens"] == 2048
    assert params["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]


async def test_temperature_sent_only_when_set() -> None:
    client = FakeAsyncOpenAI(behaviors=[_completion(), _completion()])

    llm_none = OpenAICompatLLMClient(_config(), api_key="sk-x", client=client)
    await llm_none.complete("hi")
    assert "temperature" not in client.calls[0]

    llm_temp = OpenAICompatLLMClient(
        _config(temperature=0.2), api_key="sk-x", client=client
    )
    await llm_temp.complete("hi")
    assert client.calls[1]["temperature"] == 0.2


async def test_finish_reason_length_maps_to_max_tokens() -> None:
    client = FakeAsyncOpenAI(
        behaviors=[
            FakeCompletion(choices=[FakeChoice(finish_reason="length")]),
        ]
    )
    llm = OpenAICompatLLMClient(_config(), api_key="sk-x", client=client)
    response = await llm.complete("hi")
    assert response.stop_reason == "max_tokens"
    assert response.is_truncated


async def test_complete_structured_uses_native_json_schema() -> None:
    client = FakeAsyncOpenAI(behaviors=[_completion('{"ok": true}')])
    llm = OpenAICompatLLMClient(_config(), api_key="sk-x", client=client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    response = await llm.complete_structured("give json", schema)

    fmt = client.calls[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == schema
    assert response.text == '{"ok": true}'


async def test_complete_structured_falls_back_to_prompt() -> None:
    # First call (native json_schema) fails; adapter retries prompt-embedded.
    client = FakeAsyncOpenAI(
        behaviors=[LLMError("json_schema unsupported"), _completion('{"ok": true}')]
    )
    llm = OpenAICompatLLMClient(_config(max_retries=0), api_key="sk-x", client=client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    response = await llm.complete_structured("give json", schema)

    assert response.text == '{"ok": true}'
    # Fallback used json_object mode and embedded the schema in the prompt.
    assert client.calls[1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in client.calls[1]["messages"][-1]["content"]


async def test_missing_api_key_raises() -> None:
    # No injected client and no key -> constructing the real client fails clearly.
    llm = OpenAICompatLLMClient(_config(), api_key=None)
    with pytest.raises(LLMError, match="No API key"):
        await llm.complete("hi")


# --------------------------------------------------------------------------- #
# Retries
# --------------------------------------------------------------------------- #


class _Retryable(Exception):
    status_code = 503


async def test_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OpenAICompatLLMClient,
        "_is_retryable",
        staticmethod(lambda exc: isinstance(exc, _Retryable)),
    )
    client = FakeAsyncOpenAI(
        behaviors=[_Retryable(), _Retryable(), _completion("recovered")]
    )
    llm = OpenAICompatLLMClient(_config(max_retries=3), api_key="sk-x", client=client)

    response = await llm.complete("hello")

    assert response.text == "recovered"
    assert len(client.calls) == 3
