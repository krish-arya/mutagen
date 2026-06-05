"""Tests for the subprocess-safety utilities.

These exercise the real :class:`CommandRunner` against the running Python
interpreter (a portable, always-present executable) so that timeout, retry,
and error-handling behavior is verified end to end without mocking asyncio.
"""

from __future__ import annotations

import sys

import pytest

from mutagen.infrastructure.process import (
    CommandError,
    CommandRunner,
    resolve_executable,
)


async def test_run_success_captures_stdout() -> None:
    runner = CommandRunner()
    result = await runner.run([sys.executable, "-c", "print('hello')"])
    assert result.ok
    assert result.returncode == 0
    assert "hello" in result.stdout


async def test_run_nonzero_raises_by_default() -> None:
    runner = CommandRunner()
    with pytest.raises(CommandError) as exc:
        await runner.run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert exc.value.result is not None
    assert exc.value.result.returncode == 3


async def test_run_nonzero_returned_when_check_false() -> None:
    runner = CommandRunner()
    result = await runner.run(
        [sys.executable, "-c", "import sys; sys.exit(7)"], check=False
    )
    assert not result.ok
    assert result.returncode == 7


async def test_timeout_kills_process() -> None:
    runner = CommandRunner()
    with pytest.raises(CommandError) as exc:
        await runner.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_seconds=0.5,
        )
    assert "timed out" in str(exc.value)


async def test_empty_command_rejected() -> None:
    runner = CommandRunner()
    with pytest.raises(CommandError):
        await runner.run([])


async def test_launch_failure_raises_command_error() -> None:
    runner = CommandRunner()
    with pytest.raises(CommandError):
        await runner.run(["this-executable-should-not-exist-xyz", "--help"])


async def test_retries_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flaky command should succeed once retries are exhausted-but-enough."""
    runner = CommandRunner(max_retries=3, retry_backoff_seconds=0.0)
    calls = {"n": 0}

    real_run_once = runner._run_once

    async def flaky(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] < 3:
            raise CommandError("transient")
        return await real_run_once(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "_run_once", flaky)
    result = await runner.run([sys.executable, "-c", "print('ok')"])
    assert result.ok
    assert calls["n"] == 3


async def test_retries_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CommandRunner(max_retries=2, retry_backoff_seconds=0.0)

    async def always_fail(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise CommandError("permanent")

    monkeypatch.setattr(runner, "_run_once", always_fail)
    with pytest.raises(CommandError, match="permanent"):
        await runner.run([sys.executable, "-c", "print('x')"])


def test_resolve_executable_found() -> None:
    assert resolve_executable(sys.executable)


def test_resolve_executable_missing_raises() -> None:
    with pytest.raises(CommandError):
        resolve_executable("definitely-not-a-real-binary-xyz")
