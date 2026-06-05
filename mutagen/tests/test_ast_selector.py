"""Integration tests for :class:`AstTargetSelector`.

These wire the real :class:`FunctionExtractor` and :class:`TargetRanker`
together against on-disk source, injecting a stub coverage analyzer so no
subprocess runs. They verify the end-to-end contract: ordered, validated
targets, worst-covered first, with filtering and graceful degradation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.config.run_config import RunConfig, SelectionConfig
from mutagen.core.exceptions import CoverageError
from mutagen.core.models.repo import RepoContext
from mutagen.infrastructure.selection import (
    AstTargetSelector,
    CoverageAnalyzer,
    FileCoverage,
    ProjectCoverage,
)


class _StubAnalyzer:
    """Returns a fixed :class:`ProjectCoverage` (or raises) without I/O."""

    def __init__(
        self, coverage: ProjectCoverage | None = None, *, error: bool = False
    ) -> None:
        self._coverage = coverage or ProjectCoverage()
        self._error = error

    async def analyze(
        self, root: Path, *, python: Path | None = None
    ) -> ProjectCoverage:
        if self._error:
            raise CoverageError("boom")
        return self._coverage


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _config(tmp_path: Path, **kwargs: object) -> RunConfig:
    selection = SelectionConfig(
        trivial_max_statements=1, giant_max_statements=50, **kwargs  # type: ignore[arg-type]
    )
    return RunConfig(project_root=tmp_path, selection=selection)


@pytest.fixture
def repo(tmp_path: Path) -> RepoContext:
    _write(
        tmp_path / "pkg" / "core.py",
        "def trivial():\n"
        "    return 1\n"
        "\n"
        "def compute(x):\n"
        "    total = 0\n"
        "    for i in range(x):\n"
        "        total += i\n"
        "    return total\n",
    )
    _write(
        tmp_path / "pkg" / "util.py",
        "def helper(a, b):\n"
        "    c = a + b\n"
        "    d = c * 2\n"
        "    return d\n",
    )
    return RepoContext(
        root=tmp_path,
        source_files=(Path("pkg/core.py"), Path("pkg/util.py")),
        python_version="3.11",
    )


async def test_select_returns_ordered_validated_targets(
    repo: RepoContext, tmp_path: Path
) -> None:
    # core.compute lines 5-8 partially covered; util.helper uncovered.
    coverage = ProjectCoverage(
        files={
            Path("pkg/core.py"): FileCoverage(
                path=Path("pkg/core.py"),
                executed_lines=frozenset({5, 6, 7, 8}),
            )
        }
    )
    selector = AstTargetSelector(
        _config(tmp_path), analyzer=_StubAnalyzer(coverage)
    )

    targets = await selector.select(repo)

    # Trivial function dropped; two real functions remain.
    names = [t.qualified_name for t in targets]
    assert "pkg.core.trivial" not in names
    assert set(names) == {"pkg.core.compute", "pkg.util.helper"}
    # Ordered by descending priority.
    priorities = [t.priority for t in targets]
    assert priorities == sorted(priorities, reverse=True)
    # Uncovered helper outranks the (fully covered) compute.
    assert names[0] == "pkg.util.helper"
    for t in targets:
        t.validate()


async def test_select_without_coverage_treats_all_uncovered(
    repo: RepoContext, tmp_path: Path
) -> None:
    selector = AstTargetSelector(
        _config(tmp_path), analyzer=_StubAnalyzer(ProjectCoverage())
    )
    targets = await selector.select(repo)
    assert {t.qualified_name for t in targets} == {
        "pkg.core.compute",
        "pkg.util.helper",
    }
    # All fully uncovered => priority dominated by the coverage term.
    assert all(t.priority > 0.5 for t in targets)


async def test_select_degrades_on_coverage_failure(
    repo: RepoContext, tmp_path: Path
) -> None:
    selector = AstTargetSelector(
        _config(tmp_path), analyzer=_StubAnalyzer(error=True)
    )
    targets = await selector.select(repo)
    # Coverage failure must not abort selection.
    assert len(targets) == 2


async def test_select_respects_max_targets(
    repo: RepoContext, tmp_path: Path
) -> None:
    selector = AstTargetSelector(
        _config(tmp_path, max_targets=1), analyzer=_StubAnalyzer()
    )
    targets = await selector.select(repo)
    assert len(targets) == 1


async def test_select_skips_unparsable_files(tmp_path: Path) -> None:
    _write(tmp_path / "good.py", "def f(x):\n    y = x + 1\n    return y\n")
    _write(tmp_path / "bad.py", "def broken(:\n    pass\n")
    repo = RepoContext(
        root=tmp_path,
        source_files=(Path("good.py"), Path("bad.py")),
        python_version="3.11",
    )
    selector = AstTargetSelector(_config(tmp_path), analyzer=_StubAnalyzer())
    targets = await selector.select(repo)
    # Bad file skipped; good file still yields its target.
    assert [t.qualified_name for t in targets] == ["good.f"]


def test_default_selector_builds_real_components(tmp_path: Path) -> None:
    """The adapter wires real components when none are injected."""
    selector = AstTargetSelector(RunConfig(project_root=tmp_path))
    assert isinstance(selector._analyzer, CoverageAnalyzer)
