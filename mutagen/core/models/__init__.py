"""Domain models.

Immutable, framework-agnostic dataclasses representing the core concepts of
the test-generation pipeline: the ingested repository, selected targets, the
tests generated for them, and the results of validating those tests against
mutants. Every model exposes a ``validate()`` method enforcing its invariants.
"""

from mutagen.core.models.checkpoint import RunCheckpoint, TargetCheckpoint
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.generation import GenerationInputs
from mutagen.core.models.location import SourceLocation, SourceSpan
from mutagen.core.models.outcome import (
    MutationResult,
    MutationVerdict,
    OutcomeStatus,
    TargetOutcome,
)
from mutagen.core.models.mutation_report import MutationReport
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.run import RunReport, RunResult, RunStatus, TargetStat
from mutagen.core.models.target import Target, TargetKind
from mutagen.core.models.test_run import RunnerStatus, SandboxResult

__all__ = [
    "RepoContext",
    "Target",
    "TargetKind",
    "GeneratedTest",
    "GenerationInputs",
    "RunResult",
    "RunReport",
    "RunStatus",
    "TargetStat",
    "MutationResult",
    "MutationVerdict",
    "MutationReport",
    "TargetOutcome",
    "OutcomeStatus",
    "CostInfo",
    "RunCheckpoint",
    "TargetCheckpoint",
    "SandboxResult",
    "RunnerStatus",
    "SourceLocation",
    "SourceSpan",
]
