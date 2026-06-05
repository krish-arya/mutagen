"""Tests for the CLI dispatch, using a mocked orchestrator/container."""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.cli.app import build_parser, run_cli
from mutagen.config.container import Container
from mutagen.core.models.outcome import OutcomeStatus, TargetOutcome
from mutagen.core.models.run import RunResult, RunStatus


def _config_file(tmp_path: Path, threshold: float = 0.0) -> Path:
    root = tmp_path / ".mutagen"
    path = tmp_path / "mutagen.toml"
    path.write_text(
        f'project_root = "."\nscore_threshold = {threshold}\n'
        f"[storage]\nroot = {str(root)!r}\n",
        encoding="utf-8",
    )
    return path


def _result(score_status: OutcomeStatus = OutcomeStatus.COVERED) -> RunResult:
    return RunResult(
        run_id="r1",
        status=RunStatus.SUCCEEDED,
        outcomes=(
            TargetOutcome("t0", score_status, generated_test_ids=("g0",)),
        ),
        duration_seconds=1.0,
    )


class _FakeOrchestrator:
    def __init__(self, result: RunResult) -> None:
        self._result = result
        self.progress = None
        self.executed_with: tuple[str, str] | None = None

    async def execute(self, source: str, run_id: str) -> RunResult:
        self.executed_with = (source, run_id)
        return self._result


@pytest.fixture(autouse=True)
def _restore_container():  # type: ignore[no-untyped-def]
    original = Container.provide_orchestrator
    yield
    Container.provide_orchestrator = original


def test_parser_requires_repo_for_run() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])  # missing positional repo


def test_version_flag() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0


async def test_run_success_returns_zero(tmp_path: Path) -> None:
    fake = _FakeOrchestrator(_result())
    Container.provide_orchestrator = lambda self: fake  # type: ignore[assignment]
    code = await run_cli(
        ["-c", str(_config_file(tmp_path)), "run", "./repo", "--no-progress"]
    )
    assert code == 0
    assert fake.executed_with[0] == "./repo"


async def test_run_passes_run_id_for_resume(tmp_path: Path) -> None:
    fake = _FakeOrchestrator(_result())
    Container.provide_orchestrator = lambda self: fake  # type: ignore[assignment]
    await run_cli(
        [
            "-c", str(_config_file(tmp_path)),
            "run", "./repo", "--run-id", "myrun", "--no-progress",
        ]
    )
    assert fake.executed_with == ("./repo", "myrun")


async def test_run_below_threshold_returns_two(tmp_path: Path) -> None:
    # Outcome has no mutation_results -> score 0.0, below a 0.9 threshold.
    fake = _FakeOrchestrator(_result())
    Container.provide_orchestrator = lambda self: fake  # type: ignore[assignment]
    code = await run_cli(
        [
            "-c", str(_config_file(tmp_path, threshold=0.9)),
            "run", "./repo", "--no-progress",
        ]
    )
    assert code == 2


async def test_run_handles_orchestrator_error(tmp_path: Path) -> None:
    from mutagen.core.exceptions import IngestionError

    class _Failing:
        progress = None

        async def execute(self, source, run_id):  # type: ignore[no-untyped-def]
            raise IngestionError("bad repo")

    Container.provide_orchestrator = lambda self: _Failing()  # type: ignore[assignment]
    code = await run_cli(
        ["-c", str(_config_file(tmp_path)), "run", "./repo", "--no-progress"]
    )
    assert code == 1


async def test_missing_config_returns_one(tmp_path: Path) -> None:
    code = await run_cli(
        ["-c", str(tmp_path / "absent.toml"), "run", "./repo", "--no-progress"]
    )
    assert code == 1
