"""Domain exception hierarchy.

All exceptions raised intentionally by Mutagen derive from
:class:`MutagenError`, allowing callers to catch the whole family with a
single handler while still discriminating on specific subtypes.
"""

from mutagen.core.exceptions.errors import (
    ConfigurationError,
    CoverageError,
    DependencyResolutionError,
    IngestionError,
    LLMError,
    MutagenError,
    MutationGenerationError,
    RepositoryError,
    SandboxError,
    StateTransitionError,
    TestExecutionError,
    TestGenerationError,
    ValidationError,
)

__all__ = [
    "MutagenError",
    "ValidationError",
    "ConfigurationError",
    "DependencyResolutionError",
    "StateTransitionError",
    "IngestionError",
    "MutationGenerationError",
    "TestGenerationError",
    "CoverageError",
    "SandboxError",
    "TestExecutionError",
    "LLMError",
    "RepositoryError",
]
