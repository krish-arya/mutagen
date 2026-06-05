"""Integration tests for :class:`SubprocessSandboxRunner`.

These run *real* pytest subprocesses against generated test sources written to
temp files — exercising the full path: temp-file creation, subprocess launch,
JSON-report parsing, status detection, timeout enforcement, and two-run
flakiness detection. They are skipped if ``pytest-json-report`` is unavailable.

Resource-limit (rlimit) enforcement is POSIX-only; on Windows the wall-clock
timeout is the active guard, which these tests still cover.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from mutagen.config.run_config import SandboxConfig
from mutagen.core.models.generated_test import GeneratedTest
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.test_run import RunnerStatus
from mutagen.infrastructure.sandbox import SubprocessSandboxRunner

# pytest-json-report registers as the "pytest_jsonreport" import name.
_HAS_JSON_REPORT = importlib.util.find_spec("pytest_jsonreport") is not None

pytestmark = pytest.mark.skipif(
    not _HAS_JSON_REPORT,
    reason="pytest-json-report is required for sandbox integration tests",
)


def _test(test_id: str, source: str) -> GeneratedTest:
    return GeneratedTest(
        test_id=test_id,
        target_id="target",
        module_path=f"tests/test_{test_id}.py",
        source=source,
        test_names=("test_it",),
    )


@pytest.fixture
def repo() -> RepoContext:
    return RepoContext(root=Path.cwd(), python_version="3.11")


@pytest.fixture
def runner() -> SubprocessSandboxRunner:
    # Small timeout keeps the suite fast; flakiness detection on by default.
    return SubprocessSandboxRunner(
        SandboxConfig(test_timeout_seconds=20.0, detect_flakiness=True)
    )


# --------------------------------------------------------------------------- #
# Status detection: pass / fail / error / timeout
# --------------------------------------------------------------------------- #


async def test_passing_suite(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo, [_test("pass1", "def test_it():\n    assert 2 + 2 == 4\n")]
    )
    assert result.status is RunnerStatus.PASSED
    assert result.passed
    assert result.passed_test_ids == ("pass1",)
    assert result.failed_test_ids == ()
    assert result.exit_code == 0
    result.validate()


async def test_failing_suite(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo, [_test("fail1", "def test_it():\n    assert False\n")]
    )
    assert result.status is RunnerStatus.FAILED
    assert result.failed_test_ids == ("fail1",)
    assert not result.passed


async def test_error_on_import_failure(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo,
        [
            _test(
                "err1",
                "import a_module_that_does_not_exist_xyz\n"
                "def test_it():\n    assert True\n",
            )
        ],
    )
    assert result.status is RunnerStatus.ERROR


async def test_timeout_is_detected(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo,
        [_test("slow1", "import time\ndef test_it():\n    time.sleep(60)\n")],
        timeout_seconds=1.0,
    )
    assert result.status is RunnerStatus.TIMEOUT
    # The timeout fired well before the 60s sleep would finish.
    assert result.duration_seconds < 10.0


# --------------------------------------------------------------------------- #
# Multiple tests, mixed outcomes
# --------------------------------------------------------------------------- #


async def test_mixed_pass_and_fail(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo,
        [
            _test("ok", "def test_it():\n    assert True\n"),
            _test("bad", "def test_it():\n    assert False\n"),
        ],
    )
    assert result.status is RunnerStatus.FAILED
    assert result.passed_test_ids == ("ok",)
    assert result.failed_test_ids == ("bad",)


# --------------------------------------------------------------------------- #
# Flakiness (two runs)
# --------------------------------------------------------------------------- #


async def test_flaky_test_flagged_as_error(
    runner: SubprocessSandboxRunner, repo: RepoContext, tmp_path: Path
) -> None:
    marker = tmp_path / "marker.txt"
    # Passes on the first run (no marker yet), fails on the second.
    source = (
        "from pathlib import Path\n"
        f"M = Path(r{str(marker)!r})\n"
        "def test_it():\n"
        "    first = not M.exists()\n"
        "    M.write_text('seen')\n"
        "    assert first\n"
    )
    result = await runner.run(repo, [_test("flaky", source)])
    assert result.status is RunnerStatus.ERROR
    assert result.is_flaky
    assert "flaky" in result.flaky_test_ids
    # A flaky test is neither a clean pass nor a clean fail.
    assert "flaky" not in result.passed_test_ids
    assert "flaky" not in result.failed_test_ids


async def test_stable_test_not_flagged_flaky(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo, [_test("stable", "def test_it():\n    assert True\n")]
    )
    assert not result.is_flaky
    assert result.flaky_test_ids == ()


async def test_flakiness_disabled_runs_once(repo: RepoContext, tmp_path: Path) -> None:
    runner = SubprocessSandboxRunner(SandboxConfig(detect_flakiness=False))
    marker = tmp_path / "marker.txt"
    source = (
        "from pathlib import Path\n"
        f"M = Path(r{str(marker)!r})\n"
        "def test_it():\n"
        "    first = not M.exists()\n"
        "    M.write_text('seen')\n"
        "    assert first\n"
    )
    result = await runner.run(repo, [_test("once", source)])
    # With detection off, the single (first) run passes — no flaky flag.
    assert result.status is RunnerStatus.PASSED
    assert not result.is_flaky


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


async def test_empty_test_list_errors(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(repo, [])
    assert result.status is RunnerStatus.ERROR


async def test_output_is_captured(
    runner: SubprocessSandboxRunner, repo: RepoContext
) -> None:
    result = await runner.run(
        repo,
        [
            _test(
                "printer",
                "def test_it():\n    print('SENTINEL_OUTPUT_123')\n    assert False\n",
            )
        ],
    )
    # pytest surfaces stdout of failing tests in its report output.
    assert "SENTINEL_OUTPUT_123" in result.output


async def test_resource_limits_applied_on_posix(
    repo: RepoContext,
) -> None:
    """On POSIX, an over-allocation should be killed by the memory rlimit."""
    if sys.platform == "win32":
        pytest.skip("rlimits are POSIX-only")
    runner = SubprocessSandboxRunner(
        SandboxConfig(memory_limit_mb=128, test_timeout_seconds=20.0)
    )
    # Try to allocate ~1GB, far above the 128MB cap → MemoryError → test fails
    # or the process is killed; either way it is not a clean PASS.
    source = (
        "def test_it():\n"
        "    big = bytearray(1024 * 1024 * 1024)\n"
        "    assert len(big) > 0\n"
    )
    result = await runner.run(repo, [_test("hog", source)])
    assert result.status is not RunnerStatus.PASSED
