"""Tests for the reporting layer: summarization and md/json reporters."""

from __future__ import annotations

import json
from pathlib import Path

from mutagen.config.run_config import RunConfig
from mutagen.core.models.cost import CostInfo
from mutagen.core.models.outcome import (
    MutationResult,
    MutationVerdict,
    OutcomeStatus,
    TargetOutcome,
)
from mutagen.core.models.run import RunResult, RunStatus
from mutagen.reporting import (
    CompositeReporter,
    JsonReporter,
    MarkdownReporter,
    TerminalReporter,
)
from mutagen.services import ReportingService


def _result() -> RunResult:
    kept = TargetOutcome(
        target_id="t0",
        status=OutcomeStatus.COVERED,
        generated_test_ids=("g0",),
        mutation_results=(
            MutationResult("m1", MutationVerdict.KILLED, killing_test_ids=("g0",)),
        ),
        cost=CostInfo(input_tokens=100, output_tokens=50, usd=0.01, requests=1),
    )
    discarded = TargetOutcome(
        target_id="t1",
        status=OutcomeStatus.UNCOVERED,
        generated_test_ids=("g1",),
        mutation_results=(MutationResult("m2", MutationVerdict.SURVIVED),),
        cost=CostInfo(usd=0.02, requests=1),
    )
    return RunResult(
        run_id="r1",
        status=RunStatus.SUCCEEDED,
        outcomes=(kept, discarded),
        cost=CostInfo(input_tokens=100, output_tokens=50, usd=0.03, requests=2),
        duration_seconds=12.5,
    )


def _service(tmp_path: Path) -> ReportingService:
    return ReportingService(
        config=RunConfig(project_root=tmp_path, score_threshold=0.8),
        reporter=TerminalReporter(),
    )


def test_summarize_derives_headline_stats(tmp_path: Path) -> None:
    report = _service(tmp_path).summarize(_result())
    assert report.total_targets == 2
    assert report.kept_targets == 1
    assert report.discarded_targets == 1
    assert report.total_tests_generated == 2
    assert report.cost.usd == 0.03
    assert report.duration_seconds == 12.5
    # Mean of per-target scores: t0=1.0, t1=0.0 -> 0.5.
    assert report.mutation_score == 0.5
    assert report.mutation_score_before is None  # no baseline measured
    report.validate()


def test_summarize_partial_adds_note(tmp_path: Path) -> None:
    result = RunResult(run_id="r1", status=RunStatus.PARTIAL)
    report = _service(tmp_path).summarize(result)
    assert any("partial" in n.lower() for n in report.notes)


def test_meets_threshold(tmp_path: Path) -> None:
    service = _service(tmp_path)
    report = service.summarize(_result())  # score 0.5, threshold 0.8
    assert not service.meets_threshold(report)


async def test_markdown_reporter_writes_dashboard(tmp_path: Path) -> None:
    report = _service(tmp_path).summarize(_result())
    path = tmp_path / "report.md"
    location = await MarkdownReporter(path).report(report)
    assert location == str(path)
    text = path.read_text(encoding="utf-8")
    assert "# Mutagen Report" in text
    assert "| Kept | 1 |" in text
    assert "## Mutation Score" in text
    assert "API cost" in text


async def test_json_reporter_schema(tmp_path: Path) -> None:
    report = _service(tmp_path).summarize(_result())
    path = tmp_path / "report.json"
    await JsonReporter(path).report(report)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["run_id"] == "r1"
    assert doc["mutation_score"]["after"] == 0.5
    assert doc["mutation_score"]["before"] is None
    assert doc["targets"]["kept"] == 1
    assert doc["targets"]["discarded"] == 1
    assert doc["cost"]["usd"] == 0.03
    assert len(doc["target_stats"]) == 2


async def test_composite_writes_both(tmp_path: Path) -> None:
    report = _service(tmp_path).summarize(_result())
    composite = CompositeReporter.of(
        [
            MarkdownReporter(tmp_path / "report.md"),
            JsonReporter(tmp_path / "report.json"),
        ]
    )
    location = await composite.report(report)
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.json").exists()
    assert "report.md" in location and "report.json" in location


async def test_terminal_reporter_runs(tmp_path: Path) -> None:
    report = _service(tmp_path).summarize(_result())
    # No color keeps output deterministic; just assert it does not raise.
    assert await TerminalReporter(use_color=False).report(report) == "terminal"
