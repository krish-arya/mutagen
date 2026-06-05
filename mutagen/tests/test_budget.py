"""Tests for the budget/cost tracker."""

from __future__ import annotations

from mutagen.config.run_config import OrchestratorConfig
from mutagen.core.models.cost import CostInfo
from mutagen.services import BudgetReason, BudgetTracker


class _Clock:
    """A controllable monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_unlimited_budget_never_exhausts() -> None:
    tracker = BudgetTracker(OrchestratorConfig())
    for _ in range(100):
        tracker.record_target()
    tracker.record_cost(CostInfo(usd=1000.0, input_tokens=10**9))
    assert tracker.exhausted() is None


def test_max_targets_limit() -> None:
    tracker = BudgetTracker(OrchestratorConfig(max_targets=3))
    assert tracker.exhausted() is None
    for _ in range(3):
        tracker.record_target()
    assert tracker.exhausted() is BudgetReason.MAX_TARGETS


def test_cost_limit() -> None:
    tracker = BudgetTracker(OrchestratorConfig(max_cost_usd=1.0))
    tracker.record_cost(CostInfo(usd=0.5))
    assert tracker.exhausted() is None
    tracker.record_cost(CostInfo(usd=0.6))
    assert tracker.exhausted() is BudgetReason.COST


def test_token_limit() -> None:
    tracker = BudgetTracker(OrchestratorConfig(max_tokens=1000))
    tracker.record_cost(CostInfo(input_tokens=600, output_tokens=500))
    assert tracker.exhausted() is BudgetReason.TOKENS


def test_wallclock_limit() -> None:
    clock = _Clock()
    tracker = BudgetTracker(
        OrchestratorConfig(max_wallclock_seconds=10.0),
        clock=clock,
        started_at=0.0,
    )
    clock.t = 5.0
    assert tracker.exhausted() is None
    clock.t = 10.0
    assert tracker.exhausted() is BudgetReason.WALLCLOCK


def test_accumulates_cost() -> None:
    tracker = BudgetTracker(OrchestratorConfig())
    tracker.record_cost(CostInfo(usd=1.0, input_tokens=10))
    tracker.record_cost(CostInfo(usd=2.0, output_tokens=5))
    assert tracker.cost.usd == 3.0
    assert tracker.cost.total_tokens == 15
