"""Rich-backed progress UI for the CLI.

Provides a :class:`ProgressUI` that renders a live progress bar and status line
as the orchestrator emits :class:`ProgressEvent`s, with a plain-text fallback
when ``rich`` is unavailable or output is not a TTY (CI logs, pipes). It exposes
a ``listener`` matching the orchestrator's :class:`ProgressListener` protocol.
"""

from __future__ import annotations

import sys
from types import TracebackType

from mutagen.services.progress import ProgressEvent, ProgressPhase


class ProgressUI:
    """A live progress display for a run.

    Use as a context manager; pass :attr:`listener` to the orchestrator.

    Args:
        enabled: Force-enable/disable the rich display. When ``None``, rich is
            used only if importable and stdout is a TTY.
    """

    def __init__(self, *, enabled: bool | None = None) -> None:
        self._use_rich = self._resolve(enabled)
        self._progress = None  # rich Progress, when active
        self._task_id = None

    def _resolve(self, enabled: bool | None) -> bool:
        if enabled is False:
            return False
        try:
            import rich  # noqa: F401
        except ImportError:
            return False
        if enabled is True:
            return True
        return sys.stdout.isatty()

    def __enter__(self) -> ProgressUI:
        if self._use_rich:
            from rich.progress import (
                BarColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
            )

            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
            )
            self._progress.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None

    def listener(self, event: ProgressEvent) -> None:
        """Handle one progress event (matches ``ProgressListener``)."""
        if self._use_rich and self._progress is not None:
            self._handle_rich(event)
        else:
            self._handle_plain(event)

    def _handle_rich(self, event: ProgressEvent) -> None:
        assert self._progress is not None
        if event.phase is ProgressPhase.PROCESSING and event.total is not None:
            if self._task_id is None:
                self._task_id = self._progress.add_task(
                    event.message, total=event.total
                )
            self._progress.update(
                self._task_id,
                completed=event.completed,
                description=event.message,
            )
        else:
            # Phase transitions are shown as a transient log line.
            self._progress.console.log(f"[{event.phase.value}] {event.message}")

    @staticmethod
    def _handle_plain(event: ProgressEvent) -> None:
        suffix = (
            f" ({event.completed}/{event.total})" if event.total is not None else ""
        )
        print(f"[{event.phase.value}] {event.message}{suffix}", flush=True)
