"""Subprocess-isolated :class:`SandboxRunner` adapter.

Materializes generated tests into a temporary directory, runs them under
pytest in a hardened child process, and normalizes the outcome into a
:class:`SandboxResult`.

Production concerns handled here:

* **Temporary test files** — each :class:`GeneratedTest` is written to a
  uniquely-named file in an isolated temp dir, torn down afterwards.
* **pytest-json-report** — the suite runs with ``--json-report`` so per-test
  outcomes are parsed structurally rather than scraped from stdout.
* **Timeout** — a wall-clock timeout kills and reaps an overrunning process.
* **Resource limits** — POSIX ``RLIMIT_CPU`` and ``RLIMIT_AS`` are applied via
  a ``preexec_fn``; on platforms without ``resource`` (e.g. Windows) the
  wall-clock timeout is the sole guard, logged once.
* **Status detection** — pass / fail / error / timeout are distinguished from
  the parsed report, exit code, and timeout signal.
* **Flakiness** — the suite runs twice; any test whose verdict differs between
  runs is flagged flaky, forcing an ERROR status.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import SandboxConfig
from mutagen.core.exceptions import SandboxError
from mutagen.core.interfaces import SandboxRunner
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.test_run import RunnerStatus, SandboxResult
from mutagen.infrastructure.sandbox.report_parser import ReportParser, RunReport

try:  # POSIX-only; absent on Windows.
    import resource as _resource
except ImportError:  # pragma: no cover - platform-dependent
    _resource = None  # type: ignore[assignment]

_logger = get_logger(__name__)

_REPORT_FILENAME = ".mutagen-pytest-report.json"


@dataclass(frozen=True, slots=True)
class _RawRun:
    """The raw outcome of a single pytest invocation."""

    report: RunReport
    returncode: int
    timed_out: bool
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(slots=True)
class SubprocessSandboxRunner(SandboxRunner):
    """Runs generated tests in an isolated subprocess sandbox.

    Args:
        config: Sandbox configuration (timeout, resource limits, flakiness).
        parser: Report parser; injected for testing.
    """

    config: SandboxConfig
    parser: ReportParser | None = None

    def __post_init__(self) -> None:
        self.parser = self.parser or ReportParser()

    async def run(
        self,
        context: RepoContext,
        tests: Sequence[GeneratedTest],
        *,
        mutant_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SandboxResult:
        """Run ``tests`` under pytest and report the outcome. See the port."""
        if not tests:
            return SandboxResult(status=RunnerStatus.ERROR, output="No tests to run.")

        timeout = timeout_seconds or self.config.test_timeout_seconds
        try:
            with tempfile.TemporaryDirectory(prefix="mutagen-sandbox-") as tmp:
                tmp_dir = Path(tmp)
                id_by_filename = self._materialize(tmp_dir, tests)
                runs = await self._run_suite(
                    tmp_dir, context, id_by_filename, timeout
                )
        except SandboxError:
            raise
        except OSError as exc:
            raise SandboxError(f"Failed to provision sandbox: {exc}") from exc

        return self._normalize(runs, tests)

    # ------------------------------------------------------------------ #
    # Requirement 1: temporary test files
    # ------------------------------------------------------------------ #

    @staticmethod
    def _materialize(
        tmp_dir: Path, tests: Sequence[GeneratedTest]
    ) -> dict[str, str]:
        """Write each test to a uniquely-named file; return filename -> id map.

        The filename encodes the generated-test id so the report parser can
        attribute pytest nodeids back to the originating :class:`GeneratedTest`.
        """
        id_by_filename: dict[str, str] = {}
        for test in tests:
            filename = f"test_mutagen_{test.test_id}.py"
            (tmp_dir / filename).write_text(test.source, encoding="utf-8")
            id_by_filename[filename] = test.test_id
        return id_by_filename

    # ------------------------------------------------------------------ #
    # Requirement 7: run twice for flakiness
    # ------------------------------------------------------------------ #

    async def _run_suite(
        self,
        tmp_dir: Path,
        context: RepoContext,
        id_by_filename: dict[str, str],
        timeout: float,
    ) -> list[_RawRun]:
        """Run the suite once, or twice when flakiness detection is enabled."""
        first = await self._invoke_pytest(
            tmp_dir, context, id_by_filename, timeout
        )
        if not self.config.detect_flakiness or first.timed_out:
            return [first]
        second = await self._invoke_pytest(
            tmp_dir, context, id_by_filename, timeout
        )
        return [first, second]

    # ------------------------------------------------------------------ #
    # Requirements 2-5: run pytest, capture output, enforce limits
    # ------------------------------------------------------------------ #

    async def _invoke_pytest(
        self,
        tmp_dir: Path,
        context: RepoContext,
        id_by_filename: dict[str, str],
        timeout: float,
    ) -> _RawRun:
        """Execute pytest once and return the raw, parsed outcome."""
        report_path = tmp_dir / _REPORT_FILENAME
        report_path.unlink(missing_ok=True)
        argv = self._build_argv(tmp_dir, report_path)
        env = self._build_env(context)

        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(tmp_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=self._limit_resources(),
            )
        except (OSError, ValueError) as exc:
            raise SandboxError(f"Failed to launch pytest: {exc}") from exc

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            timed_out = True
            await self._terminate(process)
            stdout_b, stderr_b = b"", b""

        duration = loop.time() - start
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        report = (
            RunReport(collection_error=True)
            if timed_out
            else self._read_report(report_path, id_by_filename)
        )
        return _RawRun(
            report=report,
            returncode=process.returncode if process.returncode is not None else -1,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

    def _build_argv(self, tmp_dir: Path, report_path: Path) -> list[str]:
        """Build the pytest argv with JSON reporting and quiet, safe defaults."""
        return [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_dir),
            "-p",
            "no:cacheprovider",
            "--json-report",
            f"--json-report-file={report_path}",
            "-q",
            "--no-header",
            "-o",
            "addopts=",  # ignore the host project's pytest addopts
        ]

    def _build_env(self, context: RepoContext) -> dict[str, str]:
        """Build a minimal, hardened environment for the child process."""
        import os

        env = dict(os.environ)
        # Make the project importable from the sandbox.
        import_root = context.root / context.import_root
        existing = env.get("PYTHONPATH", "")
        parts = [str(import_root), str(context.root)]
        if existing:
            parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(parts)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _limit_resources(self):  # type: ignore[no-untyped-def]
        """Return a ``preexec_fn`` applying rlimits, or ``None`` if unsupported.

        On POSIX, returns a callable that sets ``RLIMIT_CPU`` and ``RLIMIT_AS``
        in the child before ``exec``. On platforms without ``resource``, returns
        ``None`` (the wall-clock timeout remains the guard).
        """
        if _resource is None:
            _logger.debug(
                "resource limits unavailable on this platform; "
                "relying on wall-clock timeout only"
            )
            return None

        cpu = self.config.cpu_time_limit_seconds
        mem_bytes = self.config.memory_limit_mb * 1024 * 1024

        def _apply() -> None:  # pragma: no cover - runs in the child process
            if cpu > 0:
                _resource.setrlimit(_resource.RLIMIT_CPU, (cpu, cpu))
            if mem_bytes > 0:
                _resource.setrlimit(
                    _resource.RLIMIT_AS, (mem_bytes, mem_bytes)
                )

        return _apply

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        """Kill and reap a process that overran its timeout."""
        if process.returncode is not None:
            return
        try:
            process.kill()
        except ProcessLookupError:  # pragma: no cover - already gone
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=10.0)
        except asyncio.TimeoutError:  # pragma: no cover - stubborn child
            _logger.error("pytest did not exit after kill")

    def _read_report(
        self, report_path: Path, id_by_filename: dict[str, str]
    ) -> RunReport:
        """Read and parse the JSON report, tolerating a missing file."""
        try:
            raw = report_path.read_text(encoding="utf-8")
        except OSError:
            # No report written => pytest crashed before reporting.
            return RunReport(collection_error=True)
        assert self.parser is not None
        return self.parser.parse(raw, id_by_filename)

    # ------------------------------------------------------------------ #
    # Requirement 6: detect pass/fail/error/timeout, merge flakiness
    # ------------------------------------------------------------------ #

    def _normalize(
        self, runs: list[_RawRun], tests: Sequence[GeneratedTest]
    ) -> SandboxResult:
        """Reduce one or two raw runs into a normalized :class:`SandboxResult`."""
        first = runs[0]
        output = self._capture_output(runs)

        if first.timed_out:
            result = SandboxResult(
                status=RunnerStatus.TIMEOUT,
                duration_seconds=first.duration_seconds,
                exit_code=first.returncode,
                output=output,
            )
            result.validate()
            return result

        flaky = self._flaky_ids(runs)
        passed = first.report.passed_ids() - flaky
        failed = first.report.failed_ids() - flaky

        status = self._status(first, failed, flaky)
        result = SandboxResult(
            status=status,
            passed_test_ids=tuple(sorted(passed)),
            failed_test_ids=tuple(sorted(failed)),
            flaky_test_ids=tuple(sorted(flaky)),
            duration_seconds=sum(r.duration_seconds for r in runs),
            exit_code=first.returncode,
            output=output,
        )
        result.validate()
        return result

    @staticmethod
    def _flaky_ids(runs: list[_RawRun]) -> frozenset[str]:
        """Ids whose pass/fail verdict differed between the two runs."""
        if len(runs) < 2:
            return frozenset()
        first, second = runs[0].report, runs[1].report
        ids = set(first.verdict_by_test_id) | set(second.verdict_by_test_id)
        flaky: set[str] = set()
        for tid in ids:
            a = first.verdict_by_test_id.get(tid)
            b = second.verdict_by_test_id.get(tid)
            if a is None or b is None or a.is_success != b.is_success:
                flaky.add(tid)
        return frozenset(flaky)

    @staticmethod
    def _status(
        first: _RawRun,
        failed: frozenset[str],
        flaky: frozenset[str],
    ) -> RunnerStatus:
        """Determine the overall status from a non-timed-out run."""
        if flaky or first.report.collection_error:
            return RunnerStatus.ERROR
        if not first.report.verdict_by_test_id:
            # pytest ran but collected nothing — treat as an error.
            return RunnerStatus.ERROR
        if failed:
            return RunnerStatus.FAILED
        return RunnerStatus.PASSED

    def _capture_output(self, runs: list[_RawRun]) -> str:
        """Concatenate and truncate captured output across runs."""
        chunks: list[str] = []
        for i, run in enumerate(runs, start=1):
            label = f"--- run {i} ---" if len(runs) > 1 else ""
            chunks.append(
                "\n".join(p for p in (label, run.stdout, run.stderr) if p)
            )
        combined = "\n".join(chunks).strip()
        limit = self.config.max_output_chars
        if len(combined) > limit:
            return combined[:limit] + "\n... (truncated)"
        return combined
