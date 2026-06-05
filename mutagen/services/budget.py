"""Budget and cost tracking for a run.

:class:`BudgetTracker` centralizes the orchestrator's limit checks: how many
targets have been processed, how much wall-clock time and money/tokens have
been spent, and whether any configured ceiling has been reached. Keeping this
in one place keeps the orchestrator's control flow readable and makes the
limit logic independently testable.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from mutagen.config.run_config import OrchestratorConfig
from mutagen.core.models.cost import CostInfo


class BudgetReason(str, Enum):
    """Why the budget is considered exhausted."""

    MAX_TARGETS = "max_targets_reached"
    WALLCLOCK = "wallclock_exceeded"
    COST = "cost_limit_reached"
    TOKENS = "token_limit_reached"


@dataclass(slots=True)
class BudgetTracker:
    """Tracks spend against the configured orchestration limits.

    Safe for concurrent use: :meth:`try_reserve` and :meth:`record_cost`
    serialize their read-modify-write through an internal lock, so several
    in-flight target workers cannot collectively overshoot ``max_targets`` or
    corrupt the running cost. Synchronous accessors remain for the sequential
    path and for tests.

    Args:
        config: The orchestration limits to enforce.
        clock: Monotonic time source (injected for deterministic tests).
        started_at: Monotonic start time; defaults to ``clock()`` at creation.
    """

    config: OrchestratorConfig
    clock: Callable[[], float] = time.monotonic
    started_at: float = 0.0
    _processed: int = 0
    _cost: CostInfo = None  # type: ignore[assignment]
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = self.clock()
        if self._cost is None:
            self._cost = CostInfo.zero()

    @property
    def processed(self) -> int:
        """Number of targets processed so far."""
        return self._processed

    @property
    def cost(self) -> CostInfo:
        """Accumulated cost so far."""
        return self._cost

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds since the run started."""
        return self.clock() - self.started_at

    def record_target(self) -> None:
        """Count one processed target toward the target budget."""
        self._processed += 1

    def record_cost(self, cost: CostInfo) -> None:
        """Add ``cost`` to the running spend."""
        self._cost = self._cost.combine(cost)

    def exhausted(self) -> BudgetReason | None:
        """Return the first limit that is reached, or ``None`` if budget remains.

        Checked *before* scheduling the next target, so an in-flight target is
        always allowed to finish.
        """
        return self._exhausted()

    # ------------------------------------------------------------------ #
    # Concurrency-safe operations
    # ------------------------------------------------------------------ #

    async def try_reserve(self) -> BudgetReason | None:
        """Atomically check the budget and, if open, reserve one target slot.

        Combining the limit check with the target-count increment under a lock
        prevents several concurrent workers from each passing an open
        ``max_targets`` check and collectively overshooting it. Cost/token/
        wall-clock limits are evaluated against the spend recorded *so far* —
        concurrency can still overshoot those by up to the number of in-flight
        targets, which is the accepted "let in-flight work finish" behavior.

        Returns:
            ``None`` if a slot was reserved (the caller may proceed), or the
            :class:`BudgetReason` that blocked it (the caller must not start).
        """
        async with self._lock:
            reason = self._exhausted()
            if reason is not None:
                return reason
            self._processed += 1
            return None

    async def record_cost_safe(self, cost: CostInfo) -> None:
        """Add ``cost`` to the running spend under the lock."""
        async with self._lock:
            self._cost = self._cost.combine(cost)

    def _exhausted(self) -> BudgetReason | None:
        """Limit check shared by the sync and locked paths (no locking)."""
        cfg = self.config
        if cfg.max_targets > 0 and self._processed >= cfg.max_targets:
            return BudgetReason.MAX_TARGETS
        if (
            cfg.max_wallclock_seconds > 0
            and self.elapsed_seconds >= cfg.max_wallclock_seconds
        ):
            return BudgetReason.WALLCLOCK
        if cfg.max_cost_usd > 0 and self._cost.usd >= cfg.max_cost_usd:
            return BudgetReason.COST
        if cfg.max_tokens > 0 and self._cost.total_tokens >= cfg.max_tokens:
            return BudgetReason.TOKENS
        return None
