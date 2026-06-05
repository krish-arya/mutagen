"""Subprocess-safety utilities.

A thin, hardened wrapper around :mod:`asyncio` subprocess execution shared by
infrastructure adapters that shell out (git, venv, pip). It enforces the
project's process-safety rules in one place:

* **No shell.** Commands are always run argv-style via
  :func:`asyncio.create_subprocess_exec`; the shell is never involved, so
  there is no word-splitting or injection surface.
* **Timeouts.** Every invocation is wrapped in :func:`asyncio.wait_for`; a
  process that overruns is killed and reaped, never left dangling.
* **Retries.** Retryable failures (typically network operations) are retried
  with exponential backoff.
* **Structured logs.** Each attempt logs structured context (command, attempt,
  duration, exit code) without leaking the full environment.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.core.exceptions import IngestionError

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The captured outcome of a finished subprocess.

    Attributes:
        args: The argv that was executed.
        returncode: Process exit status.
        stdout: Captured standard output, decoded as UTF-8.
        stderr: Captured standard error, decoded as UTF-8.
        duration_seconds: Wall-clock time the process ran.
    """

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def ok(self) -> bool:
        """Whether the process exited successfully."""
        return self.returncode == 0


class CommandError(IngestionError):
    """Raised when a subprocess fails, times out, or cannot be launched.

    Attributes:
        result: The :class:`CommandResult` when the process ran to completion
            with a non-zero status, or ``None`` if it timed out or could not
            be started.
    """

    def __init__(self, message: str, *, result: CommandResult | None = None) -> None:
        super().__init__(message)
        self.result = result


def resolve_executable(name: str) -> str:
    """Resolve ``name`` to an absolute executable path.

    Resolving up front (rather than relying on the child's ``PATH`` lookup)
    keeps invocations explicit and fails fast with a clear error when a
    required tool is missing.

    Args:
        name: Executable name or path (e.g. ``"git"``).

    Returns:
        The absolute path to the executable.

    Raises:
        CommandError: If the executable cannot be found on ``PATH``.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise CommandError(f"Required executable not found on PATH: {name!r}.")
    return resolved


class CommandRunner:
    """Runs subprocesses safely with timeouts, retries, and structured logs.

    A single instance is cheap and stateless; share one per adapter. The
    ``run`` coroutine is the only entry point.
    """

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 600.0,
        max_retries: int = 0,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        """Initialize the runner.

        Args:
            default_timeout_seconds: Timeout applied when a call does not
                specify its own.
            max_retries: Default number of *additional* attempts for retryable
                calls. Individual calls may override this.
            retry_backoff_seconds: Base delay for exponential backoff.
        """
        self._default_timeout = default_timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_seconds

    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        retries: int | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Execute ``args`` as a subprocess and return its result.

        Args:
            args: The argv to execute. Must be a non-empty sequence; the shell
                is never used.
            cwd: Working directory for the child process.
            env: Environment for the child. When ``None``, the parent
                environment is inherited.
            timeout_seconds: Per-attempt timeout; falls back to the runner
                default.
            retries: Number of additional attempts on failure; falls back to
                the runner default. Retries use exponential backoff.
            check: When ``True`` (default), a non-zero exit raises
                :class:`CommandError`; when ``False``, the failing
                :class:`CommandResult` is returned to the caller.

        Returns:
            The :class:`CommandResult` of the final attempt.

        Raises:
            CommandError: If the command is empty, cannot be launched, times
                out on every attempt, or (when ``check``) exits non-zero on
                every attempt.
        """
        if not args:
            raise CommandError("Refusing to run an empty command.")

        argv = tuple(str(a) for a in args)
        timeout = (
            timeout_seconds if timeout_seconds is not None else self._default_timeout
        )
        attempts = (retries if retries is not None else self._max_retries) + 1

        last_error: CommandError | None = None
        for attempt in range(1, attempts + 1):
            log_context = {
                "command": argv[0],
                "argv_len": len(argv),
                "attempt": attempt,
                "max_attempts": attempts,
                "cwd": str(cwd) if cwd else None,
                "timeout_seconds": timeout,
            }
            try:
                result = await self._run_once(argv, cwd=cwd, env=env, timeout=timeout)
            except CommandError as exc:
                last_error = exc
                _logger.warning(
                    "subprocess attempt failed",
                    extra={"context": {**log_context, "error": str(exc)}},
                )
            else:
                if result.ok or not check:
                    _logger.debug(
                        "subprocess completed",
                        extra={
                            "context": {
                                **log_context,
                                "returncode": result.returncode,
                                "duration_seconds": round(result.duration_seconds, 3),
                            }
                        },
                    )
                    return result
                last_error = CommandError(
                    f"Command {argv[0]!r} exited with status {result.returncode}.",
                    result=result,
                )
                _logger.warning(
                    "subprocess returned non-zero",
                    extra={
                        "context": {
                            **log_context,
                            "returncode": result.returncode,
                            "stderr_tail": result.stderr[-500:],
                        }
                    },
                )

            if attempt < attempts:
                await asyncio.sleep(self._retry_backoff * (2 ** (attempt - 1)))

        assert last_error is not None  # attempts >= 1 guarantees assignment
        raise last_error

    async def _run_once(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None,
        env: Mapping[str, str] | None,
        timeout: float,
    ) -> CommandResult:
        """Run a single attempt, enforcing the timeout and reaping the child."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            raise CommandError(f"Failed to launch {argv[0]!r}: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError as exc:
            await self._terminate(process)
            raise CommandError(
                f"Command {argv[0]!r} timed out after {timeout:.0f}s."
            ) from exc

        duration = loop.time() - start
        return CommandResult(
            args=argv,
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_seconds=duration,
        )

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
        except TimeoutError:  # pragma: no cover - stubborn child
            _logger.error(
                "subprocess did not exit after kill",
                extra={"context": {"pid": process.pid}},
            )
