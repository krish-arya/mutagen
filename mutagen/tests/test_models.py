"""Tests for domain-model validation.

Exercises the ``validate()`` methods on the core domain models, covering both
the accepting and rejecting paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.core.exceptions import ValidationError
from mutagen.core.models import (
    CostInfo,
    GeneratedTest,
    MutationResult,
    MutationVerdict,
    OutcomeStatus,
    RepoContext,
    RunReport,
    RunStatus,
    SourceSpan,
    Target,
    TargetKind,
    TargetOutcome,
)


@pytest.fixture
def span() -> SourceSpan:
    return SourceSpan(path=Path("src/a.py"), start_line=1, end_line=10)


def test_repo_context_accepts_valid() -> None:
    RepoContext(root=Path.cwd(), python_version="3.11").validate()


def test_repo_context_rejects_relative_root() -> None:
    with pytest.raises(ValidationError):
        RepoContext(root=Path("rel")).validate()


def test_repo_context_rejects_absolute_source_file() -> None:
    with pytest.raises(ValidationError):
        RepoContext(root=Path.cwd(), source_files=(Path.cwd() / "a.py",)).validate()


def test_target_rejects_priority_out_of_range(span: SourceSpan) -> None:
    target = Target(
        target_id="t",
        qualified_name="a.f",
        kind=TargetKind.FUNCTION,
        span=span,
        priority=1.5,
    )
    with pytest.raises(ValidationError):
        target.validate()


def test_generated_test_requires_test_names() -> None:
    test = GeneratedTest(
        test_id="g",
        target_id="t",
        module_path="tests/test_a.py",
        source="def test_x(): assert True",
        test_names=(),
    )
    with pytest.raises(ValidationError):
        test.validate()


def test_mutation_result_killed_requires_killing_test() -> None:
    result = MutationResult(mutant_id="m", verdict=MutationVerdict.KILLED)
    with pytest.raises(ValidationError):
        result.validate()


def test_cost_info_combine_is_additive() -> None:
    a = CostInfo(input_tokens=10, output_tokens=5, usd=0.1, requests=1)
    b = CostInfo(input_tokens=1, output_tokens=2, usd=0.2, requests=1)
    combined = a.combine(b)
    assert combined.total_tokens == 18
    assert combined.requests == 2
    combined.validate()


def test_target_outcome_mutation_score() -> None:
    killed = MutationResult(
        mutant_id="m1",
        verdict=MutationVerdict.KILLED,
        killing_test_ids=("g1",),
    )
    survived = MutationResult(mutant_id="m2", verdict=MutationVerdict.SURVIVED)
    outcome = TargetOutcome(
        target_id="t",
        status=OutcomeStatus.COVERED,
        mutation_results=(killed, survived),
    )
    outcome.validate()
    assert outcome.mutation_score == 0.5


def test_run_report_rejects_covered_exceeding_total() -> None:
    report = RunReport(
        run_id="r",
        status=RunStatus.SUCCEEDED,
        total_targets=1,
        covered_targets=2,
    )
    with pytest.raises(ValidationError):
        report.validate()
