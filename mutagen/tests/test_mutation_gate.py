"""Tests for the mutmut-backed mutation gate.

The mutmut subprocess is replaced by a ``FakeRunner`` returning scripted
results, so the suite never runs mutmut. Copy-tree isolation, scoping, capping,
scoring, the keep/reject decision, and survivor feedback all run for real.
Parser and feedback components are also unit-tested directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mutagen.config.run_config import MutationConfig, RunConfig
from mutagen.core.exceptions import MutationGateError
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.location import SourceSpan
from mutagen.core.models.mutation_report import MutationReport
from mutagen.core.models.outcome import MutationResult, MutationVerdict
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target, TargetKind
from mutagen.infrastructure.gate import (
    MutmutMutationGate,
    MutmutParser,
    SurvivorFeedbackBuilder,
)
from mutagen.infrastructure.process import CommandError, CommandResult

# --------------------------------------------------------------------------- #
# Fakes & fixtures
# --------------------------------------------------------------------------- #


class FakeRunner:
    """Scripts mutmut's `run` and `result-ids <status>` calls.

    ``ids_by_status`` maps a mutmut status ("killed"/"survived"/"timeout") to
    the mutant ids returned for that bucket, mirroring ``mutmut result-ids``.
    """

    def __init__(
        self,
        ids_by_status: dict[str, list[str]] | None = None,
        *,
        run_error: Exception | None = None,
    ) -> None:
        self.ids_by_status = ids_by_status or {}
        self.run_error = run_error
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
        if self.run_error is not None and "run" in argv:
            raise self.run_error
        out = ""
        if "result-ids" in argv:
            status = argv[-1]
            out = " ".join(self.ids_by_status.get(status, []))
        return CommandResult(
            args=argv, returncode=0, stdout=out, stderr="", duration_seconds=0.1
        )

    def ran(self, needle: str) -> bool:
        return any(needle in a for argv in self.calls for a in argv)


def _ids(*pairs: tuple[str, str]) -> dict[str, list[str]]:
    """Group (mutant_id, status) pairs into a result-ids mapping."""
    out: dict[str, list[str]] = {}
    for mutant_id, status in pairs:
        out.setdefault(status, []).append(mutant_id)
    return out


def _json(*pairs: tuple[str, str]) -> str:
    """JSON results text, for the legacy MutmutParser unit tests."""
    import json

    return json.dumps({"mutants": [{"id": i, "status": s} for i, s in pairs]})


def _config(tmp_path: Path, **mutation_kwargs: object) -> RunConfig:
    return RunConfig(
        project_root=tmp_path,
        mutation=MutationConfig(**mutation_kwargs),  # type: ignore[arg-type]
    )


def _target() -> Target:
    return Target(
        target_id="t1",
        qualified_name="pkg.mod.fn",
        kind=TargetKind.FUNCTION,
        span=SourceSpan(path=Path("pkg/mod.py"), start_line=1, end_line=2),
    )


def _test(test_id: str = "g1") -> GeneratedTest:
    return GeneratedTest(
        test_id=test_id,
        target_id="t1",
        module_path="tests/t.py",
        source="from pkg.mod import fn\n\ndef test_fn():\n    assert fn(1) == 2\n",
        test_names=("test_fn",),
    )


@pytest.fixture
def repo(tmp_path: Path) -> RepoContext:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def fn(x):\n    return x + 1\n", encoding="utf-8"
    )
    return RepoContext(
        root=tmp_path,
        source_files=(Path("pkg/mod.py"),),
        python_version="3.11",
    )


async def _evaluate(
    repo: RepoContext, tmp_path: Path, runner: FakeRunner, **cfg_kwargs: object
) -> MutationReport:
    gate = MutmutMutationGate(config=_config(tmp_path, **cfg_kwargs), runner=runner)  # type: ignore[arg-type]
    return await gate.evaluate(_target(), [_test()], repo)


# --------------------------------------------------------------------------- #
# MutmutParser
# --------------------------------------------------------------------------- #


def test_parser_json_maps_verdicts() -> None:
    raw = _json(("m1", "killed"), ("m2", "survived"), ("m3", "timeout"))
    results = MutmutParser().parse(raw, killing_test_ids=("t1",))
    by_id = {r.mutant_id: r.verdict for r in results}
    assert by_id["m1"] is MutationVerdict.KILLED
    assert by_id["m2"] is MutationVerdict.SURVIVED
    assert by_id["m3"] is MutationVerdict.TIMEOUT


def test_parser_credits_killers() -> None:
    raw = _json(("m1", "killed"))
    result = MutmutParser().parse(raw, killing_test_ids=("g1", "g2"))[0]
    assert result.killing_test_ids == ("g1", "g2")


def test_parser_killed_without_known_suite_gets_placeholder() -> None:
    raw = _json(("m1", "killed"))
    result = MutmutParser().parse(raw)[0]
    # KILLED must name a killer to satisfy the model invariant.
    assert result.killing_test_ids == ("<suite>",)
    result.validate()


def test_parser_text_fallback() -> None:
    raw = "m1: killed\nm2 = survived\ngarbage line\nm3: timeout\n"
    results = MutmutParser().parse(raw)
    assert {r.mutant_id for r in results} == {"m1", "m2", "m3"}


def test_parser_emoji_sections() -> None:
    # Real mutmut 2.x `mutmut results` output: status-grouped with emoji,
    # per-file sub-headers, and comma/range mutant-number lists.
    raw = (
        "Killed 🎉 (3)\n\n---- foo.py (3) ----\n\n1-2, 5\n\n"
        "Survived 🙁 (1)\n\n---- bar.py (1) ----\n\n7\n"
    )
    results = MutmutParser().parse(raw, killing_test_ids=("t1",))
    by_id = {r.mutant_id: r.verdict for r in results}
    assert by_id["foo.py:1"] is MutationVerdict.KILLED
    assert by_id["foo.py:2"] is MutationVerdict.KILLED
    assert by_id["foo.py:5"] is MutationVerdict.KILLED
    assert by_id["bar.py:7"] is MutationVerdict.SURVIVED


def test_parser_empty_returns_empty() -> None:
    assert MutmutParser().parse("   ") == []


def test_parser_unknown_status_is_error() -> None:
    raw = _json(("m1", "weird_status"))
    assert MutmutParser().parse(raw)[0].verdict is MutationVerdict.ERROR


# --------------------------------------------------------------------------- #
# MutationReport scoring
# --------------------------------------------------------------------------- #


def test_report_score_excludes_timeouts_and_errors() -> None:
    results = (
        MutationResult("m1", MutationVerdict.KILLED, killing_test_ids=("t",)),
        MutationResult("m2", MutationVerdict.SURVIVED),
        MutationResult("m3", MutationVerdict.TIMEOUT),
        MutationResult("m4", MutationVerdict.ERROR),
    )
    report = MutationReport(target_id="t1", results=results)
    # Only m1 (killed) and m2 (survived) are scored: 1/2.
    assert report.mutation_score == 0.5
    assert len(report.survivors) == 1


def test_report_score_zero_when_nothing_scorable() -> None:
    results = (MutationResult("m1", MutationVerdict.TIMEOUT),)
    assert MutationReport(target_id="t1", results=results).mutation_score == 0.0


def test_report_validates_threshold_range() -> None:
    from mutagen.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        MutationReport(target_id="t1", threshold=1.5).validate()


# --------------------------------------------------------------------------- #
# SurvivorFeedbackBuilder
# --------------------------------------------------------------------------- #


def test_feedback_empty_when_no_survivors() -> None:
    builder = SurvivorFeedbackBuilder(MutationConfig())
    assert builder.build([], score=1.0) == ""


def test_feedback_describes_survivors() -> None:
    survivors = [
        MutationResult("m1", MutationVerdict.SURVIVED, detail="x + 1 -> x - 1"),
        MutationResult("m2", MutationVerdict.SURVIVED),
    ]
    feedback = SurvivorFeedbackBuilder(MutationConfig()).build(survivors, score=0.5)
    assert "m1" in feedback
    assert "x + 1 -> x - 1" in feedback
    assert "50%" in feedback


def test_feedback_caps_survivor_count() -> None:
    survivors = [MutationResult(f"m{i}", MutationVerdict.SURVIVED) for i in range(20)]
    builder = SurvivorFeedbackBuilder(MutationConfig(max_survivors_in_feedback=3))
    feedback = builder.build(survivors, score=0.1)
    assert "and 17 more" in feedback


# --------------------------------------------------------------------------- #
# MutmutMutationGate — full pipeline
# --------------------------------------------------------------------------- #


async def test_gate_keeps_when_score_meets_threshold(
    repo: RepoContext, tmp_path: Path
) -> None:
    runner = FakeRunner(_ids(("m1", "killed"), ("m2", "killed")))
    report = await _evaluate(repo, tmp_path, runner, score_threshold=0.8)
    assert report.kept
    assert report.mutation_score == 1.0
    assert report.survivor_feedback == ""
    report.validate()


async def test_gate_rejects_when_score_below_threshold(
    repo: RepoContext, tmp_path: Path
) -> None:
    runner = FakeRunner(_ids(("m1", "killed"), ("m2", "survived")))
    report = await _evaluate(repo, tmp_path, runner, score_threshold=0.8)
    assert not report.kept
    assert report.mutation_score == 0.5
    assert report.survivor_feedback  # feedback for the surviving mutant
    assert len(report.survivors) == 1


async def test_gate_keeps_at_exact_threshold(repo: RepoContext, tmp_path: Path) -> None:
    # 1 killed of 2 scored = 0.5; threshold 0.5 => kept (>=).
    runner = FakeRunner(_ids(("m1", "killed"), ("m2", "survived")))
    report = await _evaluate(repo, tmp_path, runner, score_threshold=0.5)
    assert report.kept


async def test_gate_queries_result_ids_per_status(
    repo: RepoContext, tmp_path: Path
) -> None:
    # The gate collects killed/survived/timeout via `mutmut result-ids`, because
    # `mutmut results` lists only survivors (which would always score 0%).
    runner = FakeRunner(_ids(("m1", "killed")))
    await _evaluate(repo, tmp_path, runner)
    queried = {argv[-1] for argv in runner.calls if "result-ids" in argv}
    assert {"killed", "survived", "timeout"} <= queried


async def test_gate_does_not_pass_unsupported_max_children(
    repo: RepoContext, tmp_path: Path
) -> None:
    # mutmut 2.5 has no --max-children option; passing it makes the command
    # error out. The mutant cap is enforced after parsing, not on the CLI.
    runner = FakeRunner(_ids(("m1", "killed")))
    await _evaluate(repo, tmp_path, runner, max_mutants=7)
    assert not any("--max-children" in argv for argv in runner.calls)


async def test_gate_caps_parsed_results(repo: RepoContext, tmp_path: Path) -> None:
    # mutmut returns more mutants than the cap; the report is truncated.
    pairs = tuple((f"m{i}", "killed") for i in range(10))
    runner = FakeRunner(_ids(*pairs))
    report = await _evaluate(repo, tmp_path, runner, max_mutants=3)
    assert report.total == 3


async def test_gate_isolates_in_copy(repo: RepoContext, tmp_path: Path) -> None:
    original = (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8")
    runner = FakeRunner(_ids(("m1", "killed")))
    await _evaluate(repo, tmp_path, runner)
    # The original repository file is never mutated in place.
    assert (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8") == original


def test_mutmut_config_scopes_runner_and_discovery(
    repo: RepoContext, tmp_path: Path
) -> None:
    # The setup.cfg drives mutmut: a scoped runner that runs only our generated
    # tests (so mutants are actually killed), plus discovery pinned away from the
    # target repo's own suite. Without the scoped runner, nothing is killed.
    gate = MutmutMutationGate(config=_config(tmp_path), runner=FakeRunner())
    workspace = tmp_path.parent / "mutagen-ws"
    workspace.mkdir(exist_ok=True)
    repo_copy = gate._provision(workspace, repo, [_test()])
    gate._write_mutmut_config(repo_copy, _target())
    cfg = (repo_copy / "setup.cfg").read_text(encoding="utf-8")
    assert "runner=" in cfg
    assert "_mutagen_tests" in cfg
    assert "paths_to_mutate=pkg/mod.py" in cfg
    ini = (repo_copy / "pytest.ini").read_text(encoding="utf-8")
    assert "testpaths = _mutagen_tests" in ini
    assert (repo_copy / "_mutagen_tests" / "__init__.py").exists()


async def test_gate_empty_tests_rejected(repo: RepoContext, tmp_path: Path) -> None:
    gate = MutmutMutationGate(config=_config(tmp_path), runner=FakeRunner())
    report = await gate.evaluate(_target(), [], repo)
    assert not report.kept
    assert report.total == 0


async def test_gate_no_mutants_rejected(repo: RepoContext, tmp_path: Path) -> None:
    runner = FakeRunner({})  # mutmut produced nothing
    report = await _evaluate(repo, tmp_path, runner, score_threshold=0.8)
    assert not report.kept
    assert report.total == 0


async def test_gate_run_failure_raises(repo: RepoContext, tmp_path: Path) -> None:
    runner = FakeRunner(run_error=CommandError("mutmut timed out"))
    gate = MutmutMutationGate(config=_config(tmp_path), runner=runner)
    with pytest.raises(MutationGateError):
        await gate.evaluate(_target(), [_test()], repo)


async def test_gate_missing_target_file_raises(tmp_path: Path) -> None:
    # Repo without the target's source file present.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "other.py").write_text("x = 1\n", encoding="utf-8")
    repo = RepoContext(
        root=tmp_path,
        source_files=(Path("pkg/other.py"),),
        python_version="3.11",
    )
    runner = FakeRunner(_ids(("m1", "killed")))
    gate = MutmutMutationGate(config=_config(tmp_path), runner=runner)
    with pytest.raises(MutationGateError):
        await gate.evaluate(_target(), [_test()], repo)
