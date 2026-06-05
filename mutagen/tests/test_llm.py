"""Tests for the LLM infrastructure layer.

All Anthropic API interaction is mocked: a :class:`FakeAsyncClient` stands in
for ``AsyncAnthropic`` and returns scripted :class:`FakeMessage` objects shaped
like real SDK responses. No network calls are made, and the real ``anthropic``
SDK is never invoked.

Coverage spans all four components — :class:`AnthropicLLMClient`,
:class:`PromptBuilder`, :class:`ResponseParser`, :class:`CostTracker` — plus
retries, backoff, timeout handling, token/cost tracking, and structured output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mutagen.config.run_config import Effort, LLMConfig
from mutagen.core.exceptions import LLMError
from mutagen.core.interfaces import LLMResponse
from mutagen.infrastructure.llm import (
    AnthropicLLMClient,
    CostTracker,
    GenerationRequest,
    PromptBuilder,
    RepairRequest,
    ResponseParseError,
    ResponseParser,
    StrengthenRequest,
    TokenUsage,
)

# --------------------------------------------------------------------------- #
# Mock SDK objects (shaped like the Anthropic SDK response)
# --------------------------------------------------------------------------- #


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeMessage:
    content: list[FakeTextBlock]
    model: str = "claude-opus-4-8"
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)
    _request_id: str = "req_test_123"


class FakeMessages:
    """Mimics ``client.messages`` with a scripted ``create``."""

    def __init__(self, owner: FakeAsyncClient) -> None:
        self._owner = owner

    async def create(self, **params: Any) -> FakeMessage:
        self._owner.calls.append(params)
        behavior = self._owner.behaviors.pop(0) if self._owner.behaviors else None
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(params)
        if isinstance(behavior, FakeMessage):
            return behavior
        return FakeMessage(content=[FakeTextBlock(text="ok")])


class FakeAsyncClient:
    """A stand-in for ``AsyncAnthropic`` recording calls and scripting results.

    ``behaviors`` is a queue consumed per ``create`` call: an exception is
    raised, a :class:`FakeMessage` is returned, a callable is invoked with the
    params, and exhaustion falls back to a default "ok" message.
    """

    def __init__(self, behaviors: list[Any] | None = None) -> None:
        self.behaviors: list[Any] = list(behaviors or [])
        self.calls: list[dict[str, Any]] = []
        self.messages = FakeMessages(self)


def _config(**kwargs: Any) -> LLMConfig:
    base: dict[str, Any] = {
        "retry_backoff_seconds": 0.0,  # keep tests fast
        "input_usd_per_mtok": 5.0,
        "output_usd_per_mtok": 25.0,
    }
    base.update(kwargs)
    return LLMConfig(**base)


def _msg(text: str = "result", **kwargs: Any) -> FakeMessage:
    return FakeMessage(content=[FakeTextBlock(text=text)], **kwargs)


# --------------------------------------------------------------------------- #
# CostTracker
# --------------------------------------------------------------------------- #


def test_cost_tracker_prices_input_and_output() -> None:
    tracker = CostTracker(_config())
    cost = tracker.price(TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost.usd == pytest.approx(30.0)  # 5 + 25
    assert cost.total_tokens == 2_000_000
    assert cost.requests == 1


def test_cost_tracker_prices_cache_tokens() -> None:
    tracker = CostTracker(_config())
    # Cache reads at 0.1x input; writes at 1.25x input.
    cost = tracker.price(
        TokenUsage(cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    )
    assert cost.usd == pytest.approx(5.0 * 0.1 + 5.0 * 1.25)


def test_cost_tracker_accumulates_total() -> None:
    tracker = CostTracker(_config())
    tracker.record(TokenUsage(input_tokens=100, output_tokens=50))
    tracker.record(TokenUsage(input_tokens=200, output_tokens=25))
    total = tracker.total
    assert total.input_tokens == 300
    assert total.output_tokens == 75
    assert total.requests == 2


def test_cost_tracker_reset() -> None:
    tracker = CostTracker(_config())
    tracker.record(TokenUsage(input_tokens=100))
    tracker.reset()
    assert tracker.total.total_tokens == 0
    assert tracker.total.requests == 0


# --------------------------------------------------------------------------- #
# PromptBuilder
# --------------------------------------------------------------------------- #


@pytest.fixture
def builder() -> PromptBuilder:
    return PromptBuilder()


def test_generation_prompt_includes_target_and_source(
    builder: PromptBuilder,
) -> None:
    prompt = builder.build_generation(
        GenerationRequest(
            qualified_name="pkg.mod.fn",
            source="def fn(x):\n    return x + 1",
            module_path="pkg.mod",
            signature="fn(x: int) -> int",
        )
    )
    assert "pkg.mod.fn" in prompt.user
    assert "return x + 1" in prompt.user
    assert "pkg.mod" in prompt.user
    assert "fn(x: int) -> int" in prompt.user
    assert "pytest" in prompt.system


def test_repair_prompt_includes_failure_output(builder: PromptBuilder) -> None:
    prompt = builder.build_repair(
        RepairRequest(
            qualified_name="pkg.mod.fn",
            test_source="def test_fn(): assert fn(1) == 2",
            failure_output="ImportError: cannot import name 'fn'",
        )
    )
    assert "ImportError" in prompt.user
    assert "test_fn" in prompt.user
    assert "repair" in prompt.system.lower()


def test_strengthen_prompt_includes_mutant(builder: PromptBuilder) -> None:
    prompt = builder.build_strengthen(
        StrengthenRequest(
            qualified_name="pkg.mod.fn",
            test_source="def test_fn(): assert fn(1) == 2",
            original_code="return x + 1",
            mutated_code="return x - 1",
            mutation_description="arithmetic operator + -> -",
        )
    )
    assert "return x - 1" in prompt.user
    assert "return x + 1" in prompt.user
    assert "arithmetic operator" in prompt.user
    assert "mutation testing" in prompt.system.lower()


def test_prompt_system_is_stable_across_calls(builder: PromptBuilder) -> None:
    # Cache-friendliness: the system prefix must be byte-identical regardless
    # of the per-target user content.
    a = builder.build_generation(
        GenerationRequest(qualified_name="a", source="x", module_path="m")
    )
    b = builder.build_generation(
        GenerationRequest(qualified_name="b", source="y", module_path="n")
    )
    assert a.system == b.system


# --------------------------------------------------------------------------- #
# ResponseParser
# --------------------------------------------------------------------------- #


@pytest.fixture
def parser() -> ResponseParser:
    return ResponseParser()


def _response(text: str, **kwargs: Any) -> LLMResponse:
    return LLMResponse(text=text, model="claude-opus-4-8", **kwargs)


def test_extract_code_plain(parser: ResponseParser) -> None:
    code = parser.extract_code(_response("def test_x():\n    assert True"))
    assert code == "def test_x():\n    assert True"


def test_extract_code_strips_fence(parser: ResponseParser) -> None:
    fenced = "```python\ndef test_x():\n    assert True\n```"
    assert parser.extract_code(_response(fenced)) == ("def test_x():\n    assert True")


def test_extract_code_refusal_raises(parser: ResponseParser) -> None:
    with pytest.raises(ResponseParseError):
        parser.extract_code(_response("", stop_reason="refusal"))


def test_extract_code_empty_raises(parser: ResponseParser) -> None:
    with pytest.raises(ResponseParseError):
        parser.extract_code(_response("   "))


def test_parse_json_valid(parser: ResponseParser) -> None:
    value = parser.parse_json(_response('{"name": "x", "n": 3}'))
    assert value == {"name": "x", "n": 3}


def test_parse_json_strips_fence(parser: ResponseParser) -> None:
    value = parser.parse_json(_response('```json\n{"ok": true}\n```'))
    assert value == {"ok": True}


def test_parse_json_invalid_raises(parser: ResponseParser) -> None:
    with pytest.raises(ResponseParseError):
        parser.parse_json(_response("{not json"))


def test_parse_json_validates_schema(parser: ResponseParser) -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
        "additionalProperties": False,
    }
    assert parser.parse_json(_response('{"n": 5}'), schema) == {"n": 5}


def test_parse_json_schema_violation_raises(parser: ResponseParser) -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
        "additionalProperties": False,
    }
    with pytest.raises(ResponseParseError):
        parser.parse_json(_response('{"n": "not-an-int"}'), schema)


def test_truncated_empty_response_message(parser: ResponseParser) -> None:
    with pytest.raises(ResponseParseError, match="truncated"):
        parser.extract_code(_response("", stop_reason="max_tokens"))


# --------------------------------------------------------------------------- #
# AnthropicLLMClient — happy path, params, usage
# --------------------------------------------------------------------------- #


async def test_complete_returns_text_and_tracks_cost() -> None:
    client = FakeAsyncClient(
        behaviors=[
            _msg(
                "generated tests",
                usage=FakeUsage(input_tokens=1000, output_tokens=500),
            )
        ]
    )
    llm = AnthropicLLMClient(_config(), client=client)

    response = await llm.complete("write tests", system="be terse")

    assert response.text == "generated tests"
    assert response.stop_reason == "end_turn"
    assert response.cost.input_tokens == 1000
    assert response.cost.output_tokens == 500
    assert response.metadata["request_id"] == "req_test_123"
    # Running total reflects the call.
    assert llm.cost_tracker.total.requests == 1


async def test_complete_sends_adaptive_thinking_and_effort() -> None:
    client = FakeAsyncClient(behaviors=[_msg()])
    llm = AnthropicLLMClient(_config(effort=Effort.XHIGH), client=client)

    await llm.complete("hello", system="sys", max_tokens=2048)

    params = client.calls[0]
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"]["effort"] == "xhigh"
    assert params["max_tokens"] == 2048
    assert params["system"] == "sys"
    assert params["messages"] == [{"role": "user", "content": "hello"}]


async def test_complete_never_sends_temperature() -> None:
    client = FakeAsyncClient(behaviors=[_msg()])
    llm = AnthropicLLMClient(_config(), client=client)
    await llm.complete("hello")
    params = client.calls[0]
    # Opus 4.7+ rejects sampling parameters — they must never be sent.
    assert "temperature" not in params
    assert "top_p" not in params
    assert "top_k" not in params


async def test_complete_respects_disabled_thinking() -> None:
    client = FakeAsyncClient(behaviors=[_msg()])
    llm = AnthropicLLMClient(_config(adaptive_thinking=False), client=client)
    await llm.complete("hello")
    assert "thinking" not in client.calls[0]


async def test_complete_structured_sets_json_schema() -> None:
    client = FakeAsyncClient(behaviors=[_msg('{"ok": true}')])
    llm = AnthropicLLMClient(_config(), client=client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    response = await llm.complete_structured("give json", schema)

    fmt = client.calls[0]["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": schema}
    assert response.text == '{"ok": true}'


# --------------------------------------------------------------------------- #
# AnthropicLLMClient — retries, backoff, error normalization
# --------------------------------------------------------------------------- #


class _Retryable(Exception):
    """Stand-in for a transient API error (status >= 500)."""

    status_code = 503


class _NonRetryable(Exception):
    """Stand-in for a client error that must not be retried."""

    status_code = 400


async def test_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make the retry predicate treat _Retryable as transient.
    monkeypatch.setattr(
        AnthropicLLMClient,
        "_is_retryable",
        staticmethod(lambda exc: isinstance(exc, _Retryable)),
    )
    client = FakeAsyncClient(behaviors=[_Retryable(), _Retryable(), _msg("recovered")])
    llm = AnthropicLLMClient(_config(max_retries=3), client=client)

    response = await llm.complete("hello")

    assert response.text == "recovered"
    assert len(client.calls) == 3


async def test_retries_exhausted_raises_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AnthropicLLMClient,
        "_is_retryable",
        staticmethod(lambda exc: isinstance(exc, _Retryable)),
    )
    client = FakeAsyncClient(behaviors=[_Retryable(), _Retryable()])
    llm = AnthropicLLMClient(_config(max_retries=1), client=client)

    with pytest.raises(LLMError):
        await llm.complete("hello")
    assert len(client.calls) == 2  # initial + 1 retry


async def test_non_retryable_error_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AnthropicLLMClient,
        "_is_retryable",
        staticmethod(lambda exc: False),
    )
    client = FakeAsyncClient(behaviors=[_NonRetryable(), _msg("unused")])
    llm = AnthropicLLMClient(_config(max_retries=5), client=client)

    with pytest.raises(LLMError):
        await llm.complete("hello")
    assert len(client.calls) == 1  # no retry on a client error


async def test_backoff_grows_exponentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "mutagen.infrastructure.llm.anthropic_client.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setattr(
        AnthropicLLMClient,
        "_is_retryable",
        staticmethod(lambda exc: isinstance(exc, _Retryable)),
    )
    client = FakeAsyncClient(behaviors=[_Retryable(), _Retryable(), _msg("ok")])
    llm = AnthropicLLMClient(
        _config(max_retries=3, retry_backoff_seconds=1.0), client=client
    )

    await llm.complete("hello")

    # 1.0 * 2**0, then 1.0 * 2**1.
    assert sleeps == [1.0, 2.0]


async def test_validated_response_rejects_blank_model() -> None:
    # A message with an empty model should fail LLMResponse.validate().
    client = FakeAsyncClient(behaviors=[_msg("x", model="")])
    llm = AnthropicLLMClient(_config(), client=client)
    with pytest.raises(Exception):  # ValidationError surfaces from validate()
        await llm.complete("hello")
