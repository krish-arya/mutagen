"""LLM-backed :class:`TestGenerator` adapter.

Orchestrates the full generation pipeline for a target:

1. **Gather** function source, imports, surrounding context, and existing test
   examples (:class:`ContextGatherer`).
2. **Build** the generation prompt, folding in style examples and any feedback
   (:class:`PromptBuilder`).
3. **Generate** by prompting the :class:`LLMClient`.
4. **Parse** the model's reply into Python source (:class:`ResponseParser`).
5. **Validate** the source — syntax, AST, pytest compatibility
   (:class:`TestValidator`).
6. **Assemble** a :class:`GeneratedTest`, attaching cost and the validity
   verdict.

An invalid test is still returned (with ``is_valid=False`` and a
``validation_error``) so downstream repair can act on it; only an LLM/transport
failure raises :class:`TestGenerationError`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import LLMError, TestGenerationError
from mutagen.core.interfaces import LLMClient, TestGenerator
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.generation import GenerationInputs
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target
from mutagen.infrastructure.generation.context_gatherer import (
    ContextGatherer,
    GatheredContext,
)
from mutagen.infrastructure.generation.validator import TestValidator
from mutagen.infrastructure.llm.prompt_builder import (
    GenerationRequest,
    PromptBuilder,
)
from mutagen.infrastructure.llm.response_parser import (
    ResponseParseError,
    ResponseParser,
)

_logger = get_logger(__name__)


@dataclass(slots=True)
class LLMTestGenerator(TestGenerator):
    """Generates tests by prompting a language model.

    Collaborators are injected for testability; all but ``config`` and
    ``llm_client`` default to standard implementations.
    """

    config: RunConfig
    llm_client: LLMClient
    gatherer: ContextGatherer | None = None
    prompt_builder: PromptBuilder | None = None
    parser: ResponseParser | None = None
    validator: TestValidator | None = None

    def __post_init__(self) -> None:
        self.gatherer = self.gatherer or ContextGatherer(self.config)
        self.prompt_builder = self.prompt_builder or PromptBuilder()
        self.parser = self.parser or ResponseParser()
        self.validator = self.validator or TestValidator()

    async def generate(
        self,
        target: Target,
        context: RepoContext,
        inputs: GenerationInputs | None = None,
    ) -> Sequence[GeneratedTest]:
        """Generate a candidate test for ``target``. See the port contract."""
        inputs = inputs or GenerationInputs()
        gathered = self._gather(target, context)
        prompt = self._build_prompt(gathered, inputs)

        try:
            response = await self.llm_client.complete(
                prompt.user, system=prompt.system
            )
        except LLMError as exc:
            raise TestGenerationError(
                f"LLM generation failed for {target.qualified_name}: {exc}"
            ) from exc

        try:
            source = self._parser.extract_code(response)
        except ResponseParseError as exc:
            # An unparsable reply is a soft failure: surface it as an invalid
            # artifact rather than aborting the whole run.
            _logger.warning(
                "could not parse generated test",
                extra={
                    "context": {
                        "target": target.qualified_name,
                        "error": str(exc),
                    }
                },
            )
            return ()

        test = self._assemble(target, context, gathered, source, response)
        _logger.info(
            "test generated",
            extra={
                "context": {
                    "target": target.qualified_name,
                    "is_valid": test.is_valid,
                    "tests": len(test.test_names),
                }
            },
        )
        return (test,)

    # ------------------------------------------------------------------ #
    # Pipeline steps
    # ------------------------------------------------------------------ #

    def _gather(self, target: Target, context: RepoContext) -> GatheredContext:
        return self._gatherer.gather(target, context)

    def _build_prompt(
        self, gathered: GatheredContext, inputs: GenerationInputs
    ):  # type: ignore[no-untyped-def]
        # Caller-supplied examples take precedence; fall back to gathered ones.
        examples = (
            inputs.style_examples
            if inputs.has_examples
            else gathered.style_examples
        )
        request = GenerationRequest(
            qualified_name=gathered.qualified_name,
            source=gathered.source,
            module_path=gathered.module_path,
            imports=gathered.imports,
            surrounding=gathered.surrounding,
            style_examples=examples,
            feedback=inputs.feedback,
        )
        return self._prompt_builder.build_generation(request)

    def _assemble(
        self,
        target: Target,
        context: RepoContext,
        gathered: GatheredContext,
        source: str,
        response,  # type: ignore[no-untyped-def]
    ) -> GeneratedTest:
        """Validate the source and build the final :class:`GeneratedTest`."""
        symbol = gathered.qualified_name.rsplit(".", 1)[-1]
        result = self._validator.validate(source, target_symbol=symbol)
        # A test must declare at least one test name to satisfy the model's
        # structural invariant; synthesize a placeholder only to carry an
        # invalid artifact through (it will not be executed).
        test_names = result.test_names or ("test_generated",)
        return GeneratedTest(
            test_id=self._test_id(target, source),
            target_id=target.target_id,
            module_path=self._module_path(target),
            source=source,
            test_names=test_names,
            cost=response.cost,
            imports=gathered.imports,
            is_valid=result.is_valid,
            validation_error=result.summary,
        )

    # ------------------------------------------------------------------ #
    # Identity helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _module_path(target: Target) -> str:
        """Repo-relative path the generated test should be written to."""
        stem = target.span.path.stem
        return str(Path("tests") / f"test_generated_{stem}.py")

    @staticmethod
    def _test_id(target: Target, source: str) -> str:
        """Stable id from the target and the generated source content."""
        digest = hashlib.sha1(
            f"{target.target_id}:{source}".encode()
        ).hexdigest()
        return digest[:16]

    # ------------------------------------------------------------------ #
    # Non-optional accessors (collaborators are set in __post_init__)
    # ------------------------------------------------------------------ #

    @property
    def _gatherer(self) -> ContextGatherer:
        assert self.gatherer is not None
        return self.gatherer

    @property
    def _prompt_builder(self) -> PromptBuilder:
        assert self.prompt_builder is not None
        return self.prompt_builder

    @property
    def _parser(self) -> ResponseParser:
        assert self.parser is not None
        return self.parser

    @property
    def _validator(self) -> TestValidator:
        assert self.validator is not None
        return self.validator
