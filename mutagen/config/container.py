"""Dependency-injection container.

The container is the composition root: it wires concrete infrastructure
adapters to the abstract ports declared in :mod:`mutagen.core.interfaces`,
and hands fully-constructed services to the application layer.

It deliberately contains no business logic — only construction and wiring.
"""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.config.run_config import RunConfig
from mutagen.core.exceptions import DependencyResolutionError
from mutagen.core.interfaces import (
    LLMClient,
    MutationGate,
    RepoIngestor,
    Reporter,
    SandboxRunner,
    Store,
    TargetSelector,
    TestGenerator,
)


@dataclass(slots=True)
class Container:
    """Resolves and caches the application's dependency graph.

    The container is constructed from a :class:`RunConfig`; each ``provide_*``
    method lazily builds and memoizes a single instance of the corresponding
    port. Concrete adapter selection is driven entirely by configuration.
    """

    config: RunConfig

    # Cached singletons, populated lazily by the provider methods.
    _llm_client: LLMClient | None = None
    _ingestor: RepoIngestor | None = None
    _selector: TargetSelector | None = None
    _generator: TestGenerator | None = None
    _sandbox_runner: SandboxRunner | None = None
    _gate: MutationGate | None = None
    _reporter: Reporter | None = None
    _store: Store | None = None

    def provide_llm_client(self) -> LLMClient:
        """Resolve the configured :class:`LLMClient`."""
        raise NotImplementedError

    def provide_ingestor(self) -> RepoIngestor:
        """Resolve the configured :class:`RepoIngestor`."""
        raise NotImplementedError

    def provide_selector(self) -> TargetSelector:
        """Resolve the configured :class:`TargetSelector`."""
        raise NotImplementedError

    def provide_generator(self) -> TestGenerator:
        """Resolve the configured :class:`TestGenerator`."""
        raise NotImplementedError

    def provide_sandbox_runner(self) -> SandboxRunner:
        """Resolve the configured :class:`SandboxRunner`."""
        raise NotImplementedError

    def provide_gate(self) -> MutationGate:
        """Resolve the configured :class:`MutationGate`."""
        raise NotImplementedError

    def provide_reporter(self) -> Reporter:
        """Resolve the configured :class:`Reporter`."""
        raise NotImplementedError

    def provide_store(self) -> Store:
        """Resolve the configured :class:`Store`."""
        raise NotImplementedError

    def _unresolved(self, port: str) -> DependencyResolutionError:
        """Build a consistent error for an unconfigured port."""
        return DependencyResolutionError(
            f"No adapter is registered for port '{port}'."
        )
