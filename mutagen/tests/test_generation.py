"""Tests for the test-generation layer.

Covers the three components — :class:`ContextGatherer`, :class:`TestValidator`,
and the orchestrating :class:`LLMTestGenerator` — plus the full pipeline. The
LLM is mocked with a ``FakeLLM`` that returns scripted source, so no real model
is called. Context gathering and validation run for real against fixtures.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import LLMError
from mutagen.core.exceptions import TestGenerationError as GenerationError
from mutagen.core.interfaces import LLMResponse
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.generation import GenerationInputs
from mutagen.core.models.location import SourceSpan
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target, TargetKind
from mutagen.infrastructure.generation import (
    ContextGatherer,
    LLMTestGenerator,
    TestValidator,
)


# --------------------------------------------------------------------------- #
# Fakes & fixtures
# --------------------------------------------------------------------------- #


class FakeLLM:
    """A scripted :class:`LLMClient`: returns fixed source, records the prompt."""

    def __init__(
        self, text: str | None = None, *, error: Exception | None = None
    ) -> None:
        self._text = (
            text
            if text is not None
            else "from pkg.mod import fn\n\ndef test_fn():\n    assert fn(1) == 2\n"
        )
        self._error = error
        self.system: str | None = None
        self.prompt: str | None = None

    async def complete(
        self, prompt: str, *, system: str | None = None, max_tokens: int | None = None
    ) -> LLMResponse:
        self.prompt = prompt
        self.system = system
        if self._error is not None:
            raise self._error
        return LLMResponse(
            text=self._text,
            model="claude-opus-4-8",
            cost=CostInfo(input_tokens=120, output_tokens=60, requests=1),
        )

    async def complete_structured(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> RepoContext:
    _write(
        tmp_path / "pkg" / "mod.py",
        "import os\n"
        "from typing import Any\n"
        "\n"
        "CONST = 42\n"
        "\n"
        "def helper(a):\n"
        "    return a * 2\n"
        "\n"
        "def fn(x):\n"
        "    return x + 1\n",
    )
    _write(
        tmp_path / "tests" / "test_existing.py",
        "def test_demo():\n    assert True\n",
    )
    return RepoContext(
        root=tmp_path,
        source_files=(Path("pkg/mod.py"),),
        test_files=(Path("tests/test_existing.py"),),
        python_version="3.11",
    )


def _target() -> Target:
    return Target(
        target_id="t1",
        qualified_name="pkg.mod.fn",
        kind=TargetKind.FUNCTION,
        span=SourceSpan(path=Path("pkg/mod.py"), start_line=9, end_line=10),
    )


# --------------------------------------------------------------------------- #
# ContextGatherer
# --------------------------------------------------------------------------- #


def test_gather_extracts_target_source(repo: RepoContext, tmp_path: Path) -> None:
    gathered = ContextGatherer(RunConfig(project_root=tmp_path)).gather(
        _target(), repo
    )
    assert "return x + 1" in gathered.source
    assert gathered.qualified_name == "pkg.mod.fn"
    assert gathered.module_path == "pkg.mod"


def test_gather_extracts_imports(repo: RepoContext, tmp_path: Path) -> None:
    gathered = ContextGatherer(RunConfig(project_root=tmp_path)).gather(
        _target(), repo
    )
    assert "import os" in gathered.imports
    assert "from typing import Any" in gathered.imports


def test_gather_surrounding_includes_sibling_signatures(
    repo: RepoContext, tmp_path: Path
) -> None:
    gathered = ContextGatherer(RunConfig(project_root=tmp_path)).gather(
        _target(), repo
    )
    # Sibling function signature and module constant, but not the target body.
    assert "def helper(a):" in gathered.surrounding
    assert "CONST = 42" in gathered.surrounding
    assert "return x + 1" not in gathered.surrounding


def test_gather_collects_test_examples(
    repo: RepoContext, tmp_path: Path
) -> None:
    gathered = ContextGatherer(RunConfig(project_root=tmp_path)).gather(
        _target(), repo
    )
    assert any("test_demo" in ex for ex in gathered.style_examples)


def test_gather_handles_unreadable_source(tmp_path: Path) -> None:
    repo = RepoContext(
        root=tmp_path,
        source_files=(Path("missing.py"),),
        python_version="3.11",
    )
    target = Target(
        target_id="t",
        qualified_name="missing.fn",
        kind=TargetKind.FUNCTION,
        span=SourceSpan(path=Path("missing.py"), start_line=1, end_line=1),
    )
    gathered = ContextGatherer(RunConfig(project_root=tmp_path)).gather(
        target, repo
    )
    assert gathered.source == ""
    assert gathered.imports == ()


# --------------------------------------------------------------------------- #
# TestValidator
# --------------------------------------------------------------------------- #


@pytest.fixture
def validator() -> TestValidator:
    return TestValidator()


def test_validator_accepts_good_test(validator: TestValidator) -> None:
    src = "from pkg.mod import fn\n\ndef test_fn():\n    assert fn(1) == 2\n"
    result = validator.validate(src, target_symbol="fn")
    assert result.is_valid
    assert result.test_names == ("test_fn",)


def test_validator_rejects_syntax_error(validator: TestValidator) -> None:
    result = validator.validate("def test_x(:\n    pass\n")
    assert not result.is_valid
    assert "Syntax error" in result.summary


def test_validator_rejects_no_test_functions(validator: TestValidator) -> None:
    src = "from pkg import fn\n\nx = fn(1)\n"
    result = validator.validate(src, target_symbol="fn")
    assert not result.is_valid
    assert any("No test functions" in e for e in result.errors)


def test_validator_rejects_missing_symbol_reference(
    validator: TestValidator,
) -> None:
    src = "import os\n\ndef test_x():\n    assert True\n"
    result = validator.validate(src, target_symbol="fn")
    assert not result.is_valid
    assert any("never referenced" in e for e in result.errors)


def test_validator_rejects_test_class_with_init(
    validator: TestValidator,
) -> None:
    src = (
        "from pkg import fn\n\n"
        "class TestThing:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "    def test_it(self):\n"
        "        assert fn(1)\n"
    )
    result = validator.validate(src, target_symbol="fn")
    assert not result.is_valid
    assert any("__init__" in e for e in result.errors)


def test_validator_discovers_class_methods(validator: TestValidator) -> None:
    src = (
        "from pkg import fn\n\n"
        "class TestThing:\n"
        "    def test_a(self):\n"
        "        assert fn(1)\n"
        "    def test_b(self):\n"
        "        assert fn(2)\n"
    )
    result = validator.validate(src, target_symbol="fn")
    assert result.is_valid
    assert "TestThing::test_a" in result.test_names
    assert "TestThing::test_b" in result.test_names


def test_validator_requires_imports(validator: TestValidator) -> None:
    src = "def test_x():\n    assert True\n"
    result = validator.validate(src)
    assert not result.is_valid
    assert any("no import" in e.lower() for e in result.errors)


# --------------------------------------------------------------------------- #
# LLMTestGenerator — full pipeline
# --------------------------------------------------------------------------- #


async def _generate(
    repo: RepoContext,
    tmp_path: Path,
    llm: FakeLLM,
    inputs: GenerationInputs | None = None,
) -> Sequence:
    gen = LLMTestGenerator(config=RunConfig(project_root=tmp_path), llm_client=llm)
    return await gen.generate(_target(), repo, inputs)


async def test_generate_produces_valid_test(
    repo: RepoContext, tmp_path: Path
) -> None:
    tests = await _generate(repo, tmp_path, FakeLLM())
    assert len(tests) == 1
    test = tests[0]
    assert test.is_valid
    assert test.validation_error == ""
    assert test.target_id == "t1"
    assert test.test_names == ("test_fn",)
    assert test.cost.total_tokens == 180
    assert test.module_path.endswith("test_generated_mod.py")
    test.validate()  # structural invariants hold


async def test_generate_strips_code_fence(
    repo: RepoContext, tmp_path: Path
) -> None:
    fenced = (
        "```python\n"
        "from pkg.mod import fn\n\n"
        "def test_fn():\n    assert fn(1) == 2\n"
        "```"
    )
    tests = await _generate(repo, tmp_path, FakeLLM(fenced))
    assert tests[0].is_valid
    assert "```" not in tests[0].source


async def test_generate_marks_invalid_test(
    repo: RepoContext, tmp_path: Path
) -> None:
    # Syntactically broken output — returned but flagged invalid.
    tests = await _generate(repo, tmp_path, FakeLLM("def test_x(:\n  pass"))
    assert len(tests) == 1
    test = tests[0]
    assert not test.is_valid
    assert test.validation_error
    test.validate()  # invalid-with-reason still satisfies structural invariants


async def test_generate_includes_context_in_prompt(
    repo: RepoContext, tmp_path: Path
) -> None:
    llm = FakeLLM()
    await _generate(repo, tmp_path, llm)
    assert llm.prompt is not None
    assert "return x + 1" in llm.prompt  # target source
    assert "import os" in llm.prompt  # imports
    assert "def helper" in llm.prompt  # surrounding
    assert "test_demo" in llm.prompt  # style example
    assert "pytest" in (llm.system or "")  # system prompt


async def test_generate_uses_supplied_examples_and_feedback(
    repo: RepoContext, tmp_path: Path
) -> None:
    llm = FakeLLM()
    inputs = GenerationInputs(
        style_examples=("def test_supplied():\n    assert 1\n",),
        feedback="Cover the negative-input case.",
    )
    await _generate(repo, tmp_path, llm, inputs)
    assert llm.prompt is not None
    assert "test_supplied" in llm.prompt  # supplied example used
    assert "negative-input" in llm.prompt  # feedback folded in
    # Supplied examples take precedence over gathered ones.
    assert "test_demo" not in llm.prompt


async def test_generate_raises_on_llm_failure(
    repo: RepoContext, tmp_path: Path
) -> None:
    llm = FakeLLM(error=LLMError("rate limited"))
    with pytest.raises(GenerationError):
        await _generate(repo, tmp_path, llm)


async def test_generate_returns_empty_on_empty_response(
    repo: RepoContext, tmp_path: Path
) -> None:
    tests = await _generate(repo, tmp_path, FakeLLM("   "))
    assert tests == ()
