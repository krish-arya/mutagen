"""Prompt construction for the test-generation pipeline.

:class:`PromptBuilder` owns the system and user prompt templates for the three
LLM-driven stages and renders them from typed inputs. Centralizing prompts
here keeps them versioned, testable, and out of the call sites — and keeps the
provider adapter free of any task-specific wording.

The three templates:

1. **Initial generation** — write tests for a target from its source.
2. **Test repair** — fix generated tests that failed to run/compile.
3. **Mutation strengthening** — improve tests so they kill a surviving mutant.

Each builder returns a :class:`Prompt` (system + user). Prompts are designed to
sit behind a frozen system prefix so they cache well: the stable instructions
live in the system string; the volatile, per-target content lives in the user
string.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Stable system prompts (cache-friendly: keep these byte-stable across calls)
# --------------------------------------------------------------------------- #

_GENERATION_SYSTEM = """\
You are an expert Python test engineer. You write correct, focused, runnable \
pytest tests for a single target function or method.

Rules:
- Output only a complete, importable Python test module. No prose, no fences.
- Use pytest. Name test functions test_*. Cover happy paths, edge cases, and \
error conditions implied by the code.
- Import the target by its fully-qualified name. Do not redefine it.
- Make each test independent and deterministic. No network, no real clock, no \
randomness without a fixed seed.
- Prefer plain asserts and pytest.raises over unittest assertions."""

_REPAIR_SYSTEM = """\
You are an expert Python test engineer repairing a generated pytest module \
that failed to run.

Rules:
- Output only the corrected, complete Python test module. No prose, no fences.
- Fix import errors, syntax errors, and incorrect assumptions revealed by the \
failure output. Preserve the original test intent.
- Do not delete tests to make the suite pass; fix them. Only remove a test if \
it is fundamentally testing impossible behavior, and keep the rest."""

_STRENGTHEN_SYSTEM = """\
You are an expert in mutation testing. A mutant of the target survived the \
current test suite, meaning the tests do not detect that specific fault.

Rules:
- Output only a complete, improved Python test module. No prose, no fences.
- Add or tighten assertions so the tests would FAIL against the described \
mutant while still PASSING against the original code.
- Keep existing passing tests; extend coverage rather than replacing it."""


@dataclass(frozen=True, slots=True)
class Prompt:
    """A rendered prompt: a stable system prefix and a per-call user message.

    Attributes:
        system: The system instruction (stable across calls of the same kind).
        user: The user message carrying the per-target details.
    """

    system: str
    user: str


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Inputs for an initial test-generation prompt.

    Attributes:
        qualified_name: Fully-qualified name of the target (for imports).
        source: Source text of the target function/method.
        module_path: Import path of the module containing the target.
        signature: Optional human-readable signature for context.
        imports: Import lines from the target's module, for scope context.
        surrounding: Trimmed sibling/module-level source the target relies on.
        style_examples: Snippets of existing project tests, for style matching.
        feedback: Optional steering note from a prior generation attempt.
        call_tree: ASCII rendering of the target's execution path (its
            transitive callees), for end-to-end test coverage.
        callee_sources: Source snippets of the target's callees, so tests can
            cover the whole execution path rather than just the entry function.
    """

    qualified_name: str
    source: str
    module_path: str
    signature: str = ""
    imports: tuple[str, ...] = field(default_factory=tuple)
    surrounding: str = ""
    style_examples: tuple[str, ...] = field(default_factory=tuple)
    feedback: str = ""
    call_tree: str = ""
    callee_sources: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RepairRequest:
    """Inputs for a test-repair prompt.

    Attributes:
        qualified_name: Fully-qualified name of the target under test.
        test_source: The failing generated test module.
        failure_output: Captured stdout/stderr from the failed run.
    """

    qualified_name: str
    test_source: str
    failure_output: str


@dataclass(frozen=True, slots=True)
class StrengthenRequest:
    """Inputs for a mutation-strengthening prompt.

    Attributes:
        qualified_name: Fully-qualified name of the target under test.
        test_source: The current (passing) test module.
        original_code: The original source of the mutated region.
        mutated_code: The surviving mutant's source.
        mutation_description: Human-readable description of the mutation.
    """

    qualified_name: str
    test_source: str
    original_code: str
    mutated_code: str
    mutation_description: str = ""


class PromptBuilder:
    """Renders prompts for each LLM-driven pipeline stage."""

    def build_generation(self, request: GenerationRequest) -> Prompt:
        """Build the initial test-generation prompt.

        Sections are appended only when present, so the prompt stays compact
        for simple targets and richer when context is available.
        """
        parts: list[str] = [
            f"Write pytest tests for `{request.qualified_name}`.",
            f"Import it from module `{request.module_path}`.",
        ]
        if request.signature:
            parts.append(f"Signature: {request.signature}")
        if request.imports:
            joined = "\n".join(request.imports)
            parts.append(f"Imports available in the module:\n```python\n{joined}\n```")
        parts.append(f"Source under test:\n```python\n{request.source}\n```")
        if request.surrounding:
            parts.append(
                "Surrounding context (signatures/constants the target may "
                f"use):\n```python\n{request.surrounding}\n```"
            )
        if request.call_tree:
            parts.append(
                "Execution path (functions the target calls — cover these "
                f"paths end-to-end):\n```text\n{request.call_tree}\n```"
            )
        for i, callee in enumerate(request.callee_sources, start=1):
            parts.append(
                f"Callee {i} on the execution path (source for reference):\n"
                f"```python\n{callee}\n```"
            )
        for i, example in enumerate(request.style_examples, start=1):
            parts.append(
                f"Existing test example {i} (match this project's style):\n"
                f"```python\n{example}\n```"
            )
        if request.feedback.strip():
            parts.append(
                f"Feedback from a previous attempt — address it:\n"
                f"{request.feedback.strip()}"
            )
        return Prompt(system=_GENERATION_SYSTEM, user="\n\n".join(parts))

    def build_repair(self, request: RepairRequest) -> Prompt:
        """Build the test-repair prompt."""
        user = (
            f"The generated tests for `{request.qualified_name}` failed to "
            f"run.\n\n"
            f"Current test module:\n"
            f"```python\n{request.test_source}\n```\n\n"
            f"Failure output:\n"
            f"```\n{request.failure_output}\n```\n\n"
            f"Return the corrected test module."
        )
        return Prompt(system=_REPAIR_SYSTEM, user=user)

    def build_strengthen(self, request: StrengthenRequest) -> Prompt:
        """Build the mutation-strengthening prompt."""
        description = (
            f"Mutation: {request.mutation_description}\n"
            if request.mutation_description
            else ""
        )
        user = (
            f"A mutant of `{request.qualified_name}` survived the test "
            f"suite.\n\n"
            f"{description}"
            f"Original code:\n```python\n{request.original_code}\n```\n\n"
            f"Surviving mutant:\n```python\n{request.mutated_code}\n```\n\n"
            f"Current tests:\n```python\n{request.test_source}\n```\n\n"
            f"Return an improved test module that kills this mutant."
        )
        return Prompt(system=_STRENGTHEN_SYSTEM, user=user)
