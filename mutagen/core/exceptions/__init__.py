"""Domain exception hierarchy.

All exceptions raised intentionally by Mutagen derive from
:class:`MutagenError`, allowing callers to catch the whole family with a
single handler while still discriminating on specific subtypes.
"""

from mutagen.core.exceptions.errors import (
    ConfigurationError,
    CoverageError,
    DependencyResolutionError,
    LLMError,
    MutagenError,
    MutationGenerationError,
    RepositoryError,
    SandboxError,
    StateTransitionError,
    TestExecutionError,
)

__all__ = [
    "MutagenError",
    "ConfigurationError",
    "DependencyResolutionError",
    "StateTransitionError",
    "MutationGenerationError",
    "CoverageError",
    "SandboxError",
    "TestExecutionError",
    "LLMError",
    "RepositoryError",
]
