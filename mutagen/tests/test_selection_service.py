"""Tests for the target-selection application service.

The :class:`SelectionService` wraps a :class:`TargetSelector` and applies the
run-level ``orchestrator.max_targets`` cap. A fake selector returns a fixed,
priority-ordered list so the cap logic is tested in isolation.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mutagen.config.run_config import OrchestratorConfig, RunConfig
from mutagen.core.interfaces import TargetSelector
from mutagen.core.models.location import SourceSpan
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target, TargetKind
from mutagen.services.selection_service import SelectionService


def _target(i: int) -> Target:
    return Target(
        target_id=f"t{i}",
        qualified_name=f"pkg.mod.fn{i}",
        kind=TargetKind.FUNCTION,
        span=SourceSpan(path=Path("pkg/mod.py"), start_line=i, end_line=i + 1),
        priority=1.0 - i * 0.1,
    )


class _FakeSelector(TargetSelector):
    def __init__(self, targets: Sequence[Target]) -> None:
        self._targets = list(targets)

    async def select(self, context: RepoContext) -> Sequence[Target]:
        return self._targets


def _config(max_targets: int) -> RunConfig:
    return RunConfig(
        project_root=Path("."),
        orchestrator=OrchestratorConfig(max_targets=max_targets),
    )


@pytest.fixture
def context() -> RepoContext:
    # The service passes context straight through to the selector; a bare
    # instance is enough since the fake selector ignores it.
    return RepoContext.__new__(RepoContext)


async def test_applies_orchestrator_cap(context: RepoContext) -> None:
    service = SelectionService(
        _config(max_targets=2), _FakeSelector([_target(i) for i in range(5)])
    )
    result = await service.select(context)
    assert [t.target_id for t in result] == ["t0", "t1"]


async def test_zero_means_unlimited(context: RepoContext) -> None:
    targets = [_target(i) for i in range(5)]
    service = SelectionService(_config(max_targets=0), _FakeSelector(targets))
    result = await service.select(context)
    assert len(result) == 5


async def test_empty_selection_is_passed_through(context: RepoContext) -> None:
    service = SelectionService(_config(max_targets=3), _FakeSelector([]))
    assert list(await service.select(context)) == []
