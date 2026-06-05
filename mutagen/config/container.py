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
    ArtifactStore,
    CoverageCollector,
    LLMClient,
    MutationGenerator,
    Reporter,
    RunRepository,
    Sandbox,
    TestRunner,
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
    _coverage_collector: CoverageCollector | None = None
    _mutation_generator: MutationGenerator | None = None
    _sandbox: Sandbox | None = None
    _test_runner: TestRunner | None = None
    _artifact_store: ArtifactStore | None = None
    _run_repository: RunRepository | None = None
    _reporter: Reporter | None = None

    def provide_llm_client(self) -> LLMClient:
        """Resolve the configured :class:`LLMClient`."""
        raise NotImplementedError

    def provide_coverage_collector(self) -> CoverageCollector:
        """Resolve the configured :class:`CoverageCollector`."""
        raise NotImplementedError

    def provide_mutation_generator(self) -> MutationGenerator:
        """Resolve the configured :class:`MutationGenerator`."""
        raise NotImplementedError

    def provide_sandbox(self) -> Sandbox:
        """Resolve the configured :class:`Sandbox`."""
        raise NotImplementedError

    def provide_test_runner(self) -> TestRunner:
        """Resolve the configured :class:`TestRunner`."""
        raise NotImplementedError

    def provide_artifact_store(self) -> ArtifactStore:
        """Resolve the configured :class:`ArtifactStore`."""
        raise NotImplementedError

    def provide_run_repository(self) -> RunRepository:
        """Resolve the configured :class:`RunRepository`."""
        raise NotImplementedError

    def provide_reporter(self) -> Reporter:
        """Resolve the configured :class:`Reporter`."""
        raise NotImplementedError

    def _unresolved(self, port: str) -> DependencyResolutionError:
        """Build a consistent error for an unconfigured port."""
        return DependencyResolutionError(
            f"No adapter is registered for port '{port}'."
        )
