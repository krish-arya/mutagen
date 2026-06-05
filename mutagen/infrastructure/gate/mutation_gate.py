"""mutmut-backed :class:`MutationGate` adapter.

Drives `mutmut` over a target's generated tests to decide whether they kill
enough mutants to be kept. The flow:

1. **Isolate** — copy the repository into a temporary directory so mutmut's
   in-place mutation never touches the original (subprocess + filesystem
   isolation).
2. **Scope** — write the generated tests into the copy and configure mutmut to
   mutate *only the target's file*, optionally capping the mutant count.
3. **Execute** — run `mutmut run` as a subprocess with a wall-clock timeout,
   then export results with `mutmut results`.
4. **Parse** — normalize mutmut's (version-varying) output into
   :class:`MutationResult` records.
5. **Score & decide** — compute the mutation score and keep the tests iff it
   meets the configured threshold.
6. **Feedback** — describe surviving mutants for a re-generation attempt.

Timeout protection, mutant caps, and subprocess isolation are all enforced
here; the mutmut subprocess is mocked in tests so the suite never runs it.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import MutationConfig, RunConfig
from mutagen.core.exceptions import MutationGateError
from mutagen.core.interfaces import MutationGate
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.mutation_report import MutationReport
from mutagen.core.models.outcome import MutationResult
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target
from mutagen.infrastructure.gate.mutmut_parser import MutmutParser
from mutagen.infrastructure.gate.survivor_feedback import SurvivorFeedbackBuilder
from mutagen.infrastructure.process import CommandError, CommandRunner

_logger = get_logger(__name__)

# Directories never copied into the isolated mutation workspace.
_IGNORED = shutil.ignore_patterns(
    ".git", ".hg", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".mutmut-cache", "build", "dist",
)


@dataclass(slots=True)
class MutmutMutationGate(MutationGate):
    """Validates generated tests by killing mutmut mutants of the target.

    Args:
        config: The run configuration; the ``mutation`` section is consulted.
        runner: Subprocess runner for mutmut; injected for tests.
        parser: mutmut output parser; injected for tests.
    """

    config: RunConfig
    runner: CommandRunner | None = None
    parser: MutmutParser | None = None

    def __post_init__(self) -> None:
        mc = self.config.mutation
        self.runner = self.runner or CommandRunner(
            default_timeout_seconds=mc.timeout_seconds, max_retries=0
        )
        self.parser = self.parser or MutmutParser()

    @property
    def _mc(self) -> MutationConfig:
        return self.config.mutation

    async def evaluate(
        self,
        target: Target,
        tests: Sequence[GeneratedTest],
        context: RepoContext,
    ) -> MutationReport:
        """Evaluate ``tests`` against mutmut mutants of ``target``."""
        if not tests:
            return self._empty_report(
                target, "No tests to evaluate."
            )

        try:
            with tempfile.TemporaryDirectory(prefix="mutagen-gate-") as tmp:
                workspace = Path(tmp)
                self._provision(workspace, context, tests)
                raw = await self._run_mutmut(workspace, target)
        except MutationGateError:
            raise
        except OSError as exc:
            raise MutationGateError(
                f"Failed to provision mutation workspace: {exc}"
            ) from exc

        test_ids = tuple(t.test_id for t in tests)
        results = self.parser.parse(raw, killing_test_ids=test_ids)
        return self._build_report(target, tests, results)

    # ------------------------------------------------------------------ #
    # Requirement: subprocess isolation (copy tree)
    # ------------------------------------------------------------------ #

    def _provision(
        self,
        workspace: Path,
        context: RepoContext,
        tests: Sequence[GeneratedTest],
    ) -> Path:
        """Copy the repo into ``workspace`` and write the generated tests."""
        repo_copy = workspace / "repo"
        try:
            shutil.copytree(context.root, repo_copy, ignore=_IGNORED)
        except OSError as exc:
            raise MutationGateError(
                f"Failed to copy repository for mutation: {exc}"
            ) from exc
        tests_dir = repo_copy / "_mutagen_tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        for test in tests:
            filename = f"test_mutagen_{test.test_id}.py"
            (tests_dir / filename).write_text(test.source, encoding="utf-8")
        return repo_copy

    # ------------------------------------------------------------------ #
    # Requirements: scope to target, caps, timeout, execute
    # ------------------------------------------------------------------ #

    async def _run_mutmut(self, workspace: Path, target: Target) -> str:
        """Run mutmut scoped to the target file and return its results text."""
        repo_copy = workspace / "repo"
        target_file = repo_copy / target.span.path
        if not target_file.is_file():
            raise MutationGateError(
                f"Target file not found in workspace: {target.span.path}."
            )

        run_argv = self._build_run_argv(repo_copy, target)
        try:
            # `mutmut run` exits non-zero when mutants survive — that is a
            # normal outcome, not a harness failure, so don't `check`.
            await self.runner.run(
                run_argv,
                cwd=repo_copy,
                timeout_seconds=self._mc.timeout_seconds,
                check=False,
            )
            results = await self.runner.run(
                self._build_results_argv(),
                cwd=repo_copy,
                timeout_seconds=self._mc.timeout_seconds,
                check=False,
            )
        except CommandError as exc:
            # A timeout or launch failure surfaces here.
            raise MutationGateError(f"mutmut execution failed: {exc}") from exc
        return results.stdout

    def _build_run_argv(self, repo_copy: Path, target: Target) -> list[str]:
        """Build the `mutmut run` argv: scope to the target file, cap mutants."""
        rel = str(target.span.path)
        argv = [
            sys.executable,
            "-m",
            "mutmut",
            "run",
            "--paths-to-mutate",
            rel,
            "--tests-dir",
            "_mutagen_tests",
            "--runner",
            f"{sys.executable} -m pytest -q -x _mutagen_tests",
            "--no-progress",
        ]
        if self._mc.max_mutants > 0:
            argv += ["--max-children", str(self._mc.max_mutants)]
        return argv

    def _build_results_argv(self) -> list[str]:
        """Build the argv that exports machine-readable results."""
        # `mutmut results` prints the per-mutant listing; the parser is
        # tolerant of JSON or text so both modern and legacy output work.
        return [sys.executable, "-m", "mutmut", "results"]

    # ------------------------------------------------------------------ #
    # Requirements: score, survivors, feedback, decision
    # ------------------------------------------------------------------ #

    def _build_report(
        self,
        target: Target,
        tests: Sequence[GeneratedTest],
        results: list[MutationResult],
    ) -> MutationReport:
        """Score the results, build feedback, and make the keep decision."""
        capped = self._apply_cap(results)
        report_results = tuple(capped)

        # Reuse the report's own score/survivor logic for a single source of
        # truth, by constructing a provisional report first.
        provisional = MutationReport(
            target_id=target.target_id,
            results=report_results,
            threshold=self._mc.score_threshold,
        )
        score = provisional.mutation_score
        survivors = provisional.survivors
        feedback = SurvivorFeedbackBuilder(self._mc).build(
            survivors, score=score
        )
        kept = score >= self._mc.score_threshold

        report = MutationReport(
            target_id=target.target_id,
            results=report_results,
            threshold=self._mc.score_threshold,
            kept=kept,
            survivor_feedback=feedback,
            detail="" if report_results else "mutmut produced no mutants.",
        )
        report.validate()
        _logger.info(
            "mutation gate evaluated",
            extra={
                "context": {
                    "target": target.qualified_name,
                    "mutants": report.total,
                    "score": round(score, 3),
                    "kept": kept,
                    "survivors": len(survivors),
                }
            },
        )
        return report

    def _apply_cap(
        self, results: list[MutationResult]
    ) -> list[MutationResult]:
        """Truncate results to the configured mutant cap, if any."""
        cap = self._mc.max_mutants
        if cap > 0 and len(results) > cap:
            return results[:cap]
        return results

    def _empty_report(self, target: Target, detail: str) -> MutationReport:
        """Build a kept=False report for the degenerate (no-mutants) case."""
        report = MutationReport(
            target_id=target.target_id,
            threshold=self._mc.score_threshold,
            kept=False,
            detail=detail,
        )
        report.validate()
        return report
