"""Generation adapters implementing :class:`TestGenerator`.

The :class:`LLMTestGenerator` composes three focused collaborators:

* :class:`ContextGatherer` — gathers source, imports, surrounding context, and
  existing test examples from the repository snapshot;
* the LLM layer's prompt builder, client, and parser; and
* :class:`TestValidator` — syntax, AST, and pytest-compatibility validation.
"""

from mutagen.infrastructure.generation.context_gatherer import (
    ContextGatherer,
    GatheredContext,
)
from mutagen.infrastructure.generation.llm_generator import LLMTestGenerator
from mutagen.infrastructure.generation.validator import (
    TestValidator,
    ValidationResult,
)

__all__ = [
    "LLMTestGenerator",
    "ContextGatherer",
    "GatheredContext",
    "TestValidator",
    "ValidationResult",
]
