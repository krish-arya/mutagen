"""Copy-tree :class:`Sandbox` adapter.

Provisions isolation by copying the project tree into a temporary directory,
applying the mutant there, and cleaning up on exit.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator

from mutagen.config.run_config import SandboxConfig
from mutagen.core.interfaces import Sandbox, SandboxContext
from mutagen.core.models.mutant import Mutant


@dataclass(slots=True)
class CopyTreeSandbox(Sandbox):
    """Isolates each mutant evaluation in a copied project tree."""

    config: SandboxConfig

    @asynccontextmanager
    async def provision(self, mutant: Mutant) -> AsyncIterator[SandboxContext]:
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator
