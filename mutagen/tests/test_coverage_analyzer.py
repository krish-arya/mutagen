"""Tests for :class:`CoverageAnalyzer`.

Report parsing is verified directly against coverage.py-shaped JSON (no
subprocess). The end-to-end ``analyze`` flow is verified with a fake runner
that writes a report, so the orchestration is covered without running pytest.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import CoverageError
from mutagen.infrastructure.process import CommandError, CommandResult
from mutagen.infrastructure.selection import CoverageAnalyzer


def _report(files: dict[str, dict[str, list[int]]]) -> str:
    return json.dumps({"files": files})


@pytest.fixture
def analyzer(tmp_path: Path) -> CoverageAnalyzer:
    return CoverageAnalyzer(RunConfig(project_root=tmp_path))


def test_parse_report_relativizes_and_extracts(
    analyzer: CoverageAnalyzer, tmp_path: Path
) -> None:
    raw = _report(
        {
            str(tmp_path / "pkg" / "a.py"): {
                "executed_lines": [1, 2, 3],
                "missing_lines": [4, 5],
            }
        }
    )
    cov = analyzer.parse_report(raw, tmp_path)
    fc = cov.for_file(Path("pkg/a.py"))
    assert fc is not None
    assert fc.executed_lines == frozenset({1, 2, 3})
    assert fc.missing_lines == frozenset({4, 5})
    assert fc.executable_lines == frozenset({1, 2, 3, 4, 5})
    assert fc.covered(2)
    assert not fc.covered(4)


def test_parse_report_keeps_relative_paths(
    analyzer: CoverageAnalyzer, tmp_path: Path
) -> None:
    cov = analyzer.parse_report(
        _report({"pkg/b.py": {"executed_lines": [1]}}), tmp_path
    )
    assert cov.for_file(Path("pkg/b.py")) is not None


def test_parse_report_invalid_json_raises(
    analyzer: CoverageAnalyzer, tmp_path: Path
) -> None:
    with pytest.raises(CoverageError):
        analyzer.parse_report("{not json", tmp_path)


def test_parse_report_missing_files_section_raises(
    analyzer: CoverageAnalyzer, tmp_path: Path
) -> None:
    with pytest.raises(CoverageError):
        analyzer.parse_report(json.dumps({"meta": {}}), tmp_path)


def test_parse_report_file_missing_raises(
    analyzer: CoverageAnalyzer, tmp_path: Path
) -> None:
    with pytest.raises(CoverageError):
        analyzer.parse_report_file(tmp_path / "absent.json", tmp_path)


def test_empty_coverage_is_empty(
    analyzer: CoverageAnalyzer, tmp_path: Path
) -> None:
    cov = analyzer.parse_report(_report({}), tmp_path)
    assert cov.is_empty


class _Runner:
    """Fake runner: writes a coverage report on the ``coverage json`` call."""

    def __init__(self, report: str, *, export_error: bool = False) -> None:
        self.report = report
        self.export_error = export_error
        self.calls: list[tuple[str, ...]] = []

    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: object | None = None,
        timeout_seconds: float | None = None,
        retries: int | None = None,
        check: bool = True,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        if "json" in argv:
            if self.export_error:
                raise CommandError("coverage json failed")
            out_index = argv.index("-o") + 1
            Path(argv[out_index]).write_text(self.report, encoding="utf-8")
        return CommandResult(
            args=argv, returncode=0, stdout="", stderr="", duration_seconds=0.0
        )


async def test_analyze_runs_suite_and_parses(tmp_path: Path) -> None:
    report = _report({"pkg/a.py": {"executed_lines": [1, 2]}})
    runner = _Runner(report)
    analyzer = CoverageAnalyzer(RunConfig(project_root=tmp_path), runner=runner)  # type: ignore[arg-type]

    cov = await analyzer.analyze(tmp_path)

    assert cov.for_file(Path("pkg/a.py")).executed_lines == frozenset({1, 2})
    assert any("run" in c for c in runner.calls)
    assert any("json" in c for c in runner.calls)


async def test_analyze_export_failure_raises(tmp_path: Path) -> None:
    runner = _Runner("", export_error=True)
    analyzer = CoverageAnalyzer(RunConfig(project_root=tmp_path), runner=runner)  # type: ignore[arg-type]
    with pytest.raises(CoverageError):
        await analyzer.analyze(tmp_path)
