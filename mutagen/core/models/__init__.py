"""Domain models.

Immutable, framework-agnostic dataclasses that represent the core concepts
of the mutation-testing domain. These types carry no behavior beyond simple
derived properties and validation.
"""

from mutagen.core.models.coverage import CoverageReport, FileCoverage
from mutagen.core.models.location import SourceLocation, SourceSpan
from mutagen.core.models.mutant import Mutant, MutantResult, Mutation
from mutagen.core.models.run import RunResult, RunSummary
from mutagen.core.models.target import MutationTarget, TargetModule
from mutagen.core.models.test import TestCase, TestOutcome, TestSuiteResult

__all__ = [
    "CoverageReport",
    "FileCoverage",
    "SourceLocation",
    "SourceSpan",
    "Mutant",
    "MutantResult",
    "Mutation",
    "RunResult",
    "RunSummary",
    "MutationTarget",
    "TargetModule",
    "TestCase",
    "TestOutcome",
    "TestSuiteResult",
]
