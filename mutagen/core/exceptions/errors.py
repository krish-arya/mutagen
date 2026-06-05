"""Concrete exception types for the Mutagen domain."""

from __future__ import annotations


class MutagenError(Exception):
    """Base class for all Mutagen-raised exceptions.

    Attributes:
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(MutagenError):
    """Raised when a domain model fails its invariant checks.

    Raised by the ``validate()`` method of domain dataclasses when their
    fields are internally inconsistent or out of range.
    """


class ConfigurationError(MutagenError):
    """Raised when configuration is missing, malformed, or invalid."""


class DependencyResolutionError(MutagenError):
    """Raised when the DI container cannot resolve a requested dependency."""


class StateTransitionError(MutagenError):
    """Raised when an illegal run-state transition is attempted."""


class IngestionError(MutagenError):
    """Raised when a repository cannot be ingested into a RepoContext."""


class MutationGenerationError(MutagenError):
    """Raised when mutants cannot be generated for a target."""


class MutationGateError(MutagenError):
    """Raised when the mutation gate cannot run or parse a mutation run."""


class TestGenerationError(MutagenError):
    """Raised when tests cannot be generated for a target."""


class CoverageError(MutagenError):
    """Raised when coverage collection fails."""


class SandboxError(MutagenError):
    """Raised when a sandbox cannot be provisioned or torn down."""


class TestExecutionError(MutagenError):
    """Raised when the test runner fails to execute the suite."""


class LLMError(MutagenError):
    """Raised when an LLM request fails or returns an unusable response."""


class RepositoryError(MutagenError):
    """Raised when persisting or retrieving a run fails."""
