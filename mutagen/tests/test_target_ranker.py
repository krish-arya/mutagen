"""Tests for :class:`TargetRanker`.

Cover the four responsibilities: coverage-fraction math, the three filters,
priority scoring with weighting, and lowest-coverage-first ordering. Inputs
are constructed :class:`ExtractedFunction` records so ranking is tested in
isolation from AST parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.config.run_config import SelectionConfig
from mutagen.core.models.target import TargetKind
from mutagen.infrastructure.selection import (
    FileCoverage,
    TargetRanker,
)
from mutagen.infrastructure.selection.function_extractor import ExtractedFunction


def _func(
    name: str,
    *,
    statements: int = 5,
    body_lines: frozenset[int] = frozenset({10, 11, 12, 13, 14}),
    decorators: tuple[str, ...] = (),
    start: int = 10,
    end: int = 14,
) -> ExtractedFunction:
    return ExtractedFunction(
        qualified_name=name,
        kind=TargetKind.FUNCTION,
        start_line=start,
        end_line=end,
        body_lines=body_lines,
        statement_count=statements,
        decorators=decorators,
    )


@pytest.fixture
def config() -> SelectionConfig:
    return SelectionConfig(trivial_max_statements=1, giant_max_statements=20)


@pytest.fixture
def ranker(config: SelectionConfig) -> TargetRanker:
    return TargetRanker(config)


# ---------------------------------------------------------------------- #
# Coverage fraction
# ---------------------------------------------------------------------- #


def test_coverage_fraction_partial() -> None:
    func = _func("f", body_lines=frozenset({1, 2, 3, 4}))
    cov = FileCoverage(path=Path("m.py"), executed_lines=frozenset({1, 2}))
    assert TargetRanker.coverage_fraction(func, cov) == 0.5


def test_coverage_fraction_none_means_uncovered() -> None:
    func = _func("f", body_lines=frozenset({1, 2}))
    assert TargetRanker.coverage_fraction(func, None) == 0.0


def test_coverage_fraction_no_body_means_covered() -> None:
    func = _func("f", body_lines=frozenset())
    assert TargetRanker.coverage_fraction(func, None) == 1.0


# ---------------------------------------------------------------------- #
# Filters
# ---------------------------------------------------------------------- #


def test_trivial_function_filtered(ranker: TargetRanker) -> None:
    targets = ranker.rank_file(Path("m.py"), [_func("t", statements=1)], None)
    assert targets == []


def test_giant_function_filtered(ranker: TargetRanker) -> None:
    targets = ranker.rank_file(Path("m.py"), [_func("g", statements=21)], None)
    assert targets == []


def test_property_getter_filtered(ranker: TargetRanker) -> None:
    prop = _func("C.p", statements=3, decorators=("property",))
    assert ranker.rank_file(Path("m.py"), [prop], None) == []


def test_property_kept_when_disabled() -> None:
    ranker = TargetRanker(
        SelectionConfig(
            trivial_max_statements=1,
            giant_max_statements=20,
            exclude_property_getters=False,
        )
    )
    prop = _func("C.p", statements=3, decorators=("property",))
    assert len(ranker.rank_file(Path("m.py"), [prop], None)) == 1


def test_normal_function_kept(ranker: TargetRanker) -> None:
    targets = ranker.rank_file(Path("m.py"), [_func("ok", statements=5)], None)
    assert len(targets) == 1
    assert targets[0].qualified_name == "m.ok"


# ---------------------------------------------------------------------- #
# Scoring & ordering
# ---------------------------------------------------------------------- #


def test_uncovered_outranks_covered(ranker: TargetRanker) -> None:
    covered = _func("covered", body_lines=frozenset({10, 11, 12, 13, 14}))
    uncovered = _func("uncovered", body_lines=frozenset({20, 21, 22, 23, 24}))
    cov = FileCoverage(
        path=Path("m.py"),
        executed_lines=frozenset({10, 11, 12, 13, 14}),  # covers `covered`
    )
    targets = ranker.rank_file(Path("m.py"), [covered, uncovered], cov)
    assert [t.qualified_name for t in targets] == ["m.uncovered", "m.covered"]
    assert targets[0].priority > targets[1].priority


def test_larger_outranks_smaller_at_equal_coverage(
    ranker: TargetRanker,
) -> None:
    small = _func("small", statements=3, body_lines=frozenset({1}))
    large = _func("large", statements=18, body_lines=frozenset({1}))
    # Both fully uncovered (coverage None).
    targets = ranker.rank_file(Path("m.py"), [large, small], None)
    assert targets[0].qualified_name == "m.large"
    assert targets[0].priority > targets[1].priority


def test_priority_within_unit_interval(ranker: TargetRanker) -> None:
    targets = ranker.rank_file(
        Path("m.py"), [_func("a", statements=10)], None
    )
    assert 0.0 <= targets[0].priority <= 1.0


def test_ordering_is_deterministic(ranker: TargetRanker) -> None:
    funcs = [_func(n, statements=5) for n in ("c", "a", "b")]
    # All identical coverage/size => name tiebreak gives stable order.
    names = [t.qualified_name for t in ranker.rank_file(Path("m.py"), funcs, None)]
    assert names == sorted(names)


def test_targets_validate(ranker: TargetRanker) -> None:
    targets = ranker.rank_file(Path("pkg/m.py"), [_func("f", statements=5)], None)
    for t in targets:
        t.validate()  # must not raise
    assert targets[0].qualified_name == "pkg.m.f"
    assert targets[0].kind is TargetKind.FUNCTION


def test_target_id_is_stable(ranker: TargetRanker) -> None:
    func = _func("f", statements=5)
    a = ranker.rank_file(Path("m.py"), [func], None)[0]
    b = ranker.rank_file(Path("m.py"), [func], None)[0]
    assert a.target_id == b.target_id
