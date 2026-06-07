"""Dependency-injection container.

The container is the composition root: it wires concrete infrastructure
adapters to the abstract ports declared in :mod:`mutagen.core.interfaces`, and
assembles the application services. It deliberately contains no business logic —
only construction and wiring — and is the single place that imports concrete
adapters, keeping every other layer dependent on abstractions alone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import (
    CallGraphAnalyzer,
    CheckpointStore,
    LLMClient,
    MutationGate,
    RepoIngestor,
    Reporter,
    SandboxRunner,
    Store,
    TargetSelector,
    TestGenerator,
    TestRetriever,
)
from mutagen.services.orchestrator import PipelineOrchestrator
from mutagen.services.reporting_service import ReportingService
from mutagen.services.selection_service import SelectionService
from mutagen.services.target_processor import TargetProcessor

if TYPE_CHECKING:
    from mutagen.infrastructure.store.sqlite_store import _Database


class Container:
    """Resolves and caches the application's dependency graph.

    Constructed from a :class:`RunConfig`; each ``provide_*`` method lazily
    builds and memoizes a single instance of the corresponding port or service.
    Concrete adapter selection is driven by configuration.
    """

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self._cache: dict[str, object] = {}

    def _memo(self, key: str, factory: Callable[[], object]) -> object:
        """Return a cached singleton, building it via ``factory`` on first use."""
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    # ------------------------------------------------------------------ #
    # Ports
    # ------------------------------------------------------------------ #

    def provide_llm_client(self) -> LLMClient:
        """Resolve the configured :class:`LLMClient` for the active provider.

        ``anthropic`` uses the native Anthropic adapter; ``openai``, ``gemini``,
        and ``openrouter`` share the OpenAI-compatible adapter, which reads its
        API key from the environment variable named by ``config.llm.api_key_env``.
        """
        import os

        from mutagen.infrastructure.llm import (
            AnthropicLLMClient,
            OpenAICompatLLMClient,
        )

        def build() -> LLMClient:
            llm = self.config.llm
            if llm.provider == "anthropic":
                return AnthropicLLMClient(llm)
            if llm.provider in ("openai", "gemini", "openrouter"):
                return OpenAICompatLLMClient(
                    llm, api_key=os.environ.get(llm.api_key_env)
                )
            raise ValueError(f"Unknown LLM provider: {llm.provider!r}")

        return self._memo("llm", build)  # type: ignore[return-value]

    def provide_ingestor(self) -> RepoIngestor:
        """Resolve the configured :class:`RepoIngestor`."""
        from mutagen.infrastructure.ingest import FilesystemRepoIngestor

        return self._memo("ingestor", lambda: FilesystemRepoIngestor(self.config))  # type: ignore[return-value]

    def provide_selector(self) -> TargetSelector:
        """Resolve the configured :class:`TargetSelector`."""
        from mutagen.infrastructure.selection import AstTargetSelector

        return self._memo("selector", lambda: AstTargetSelector(self.config))  # type: ignore[return-value]

    def provide_call_graph_analyzer(self) -> CallGraphAnalyzer | None:
        """Resolve the :class:`CallGraphAnalyzer`, or ``None`` if disabled."""
        if not self.config.generation.use_call_graph:
            return None
        from mutagen.infrastructure.selection import AstCallGraphAnalyzer

        return self._memo("call_graph", AstCallGraphAnalyzer)  # type: ignore[return-value]

    def provide_retriever(self) -> TestRetriever | None:
        """Resolve the :class:`TestRetriever`, or ``None`` if disabled."""
        if not self.config.generation.use_retrieval:
            return None
        from mutagen.infrastructure.retrieval import (
            EmbeddingTestRetriever,
            HashingEmbeddingProvider,
        )

        def build() -> TestRetriever:
            embedder = HashingEmbeddingProvider(self.config.generation.embedding_dim)
            return EmbeddingTestRetriever(embedder)

        return self._memo("retriever", build)  # type: ignore[return-value]

    def provide_generator(self) -> TestGenerator:
        """Resolve the configured :class:`TestGenerator`.

        Builds a :class:`ContextGatherer` enriched with the optional call-graph
        analyzer and test retriever (each present only when enabled in config),
        so semantic and retrieval-augmented context flow into the prompt.
        """
        from mutagen.infrastructure.generation import ContextGatherer, LLMTestGenerator

        def build() -> TestGenerator:
            gatherer = ContextGatherer(
                self.config,
                call_graph_analyzer=self.provide_call_graph_analyzer(),
                retriever=self.provide_retriever(),
            )
            return LLMTestGenerator(
                config=self.config,
                llm_client=self.provide_llm_client(),
                gatherer=gatherer,
            )

        return self._memo("generator", build)  # type: ignore[return-value]

    def provide_sandbox_runner(self) -> SandboxRunner:
        """Resolve the configured :class:`SandboxRunner`."""
        from mutagen.infrastructure.sandbox import SubprocessSandboxRunner

        return self._memo(
            "sandbox", lambda: SubprocessSandboxRunner(self.config.sandbox)
        )  # type: ignore[return-value]

    def provide_gate(self) -> MutationGate:
        """Resolve the configured :class:`MutationGate`."""
        from mutagen.infrastructure.gate import MutmutMutationGate

        return self._memo("gate", lambda: MutmutMutationGate(config=self.config))  # type: ignore[return-value]

    def provide_reporter(self) -> Reporter:
        """Resolve a composite :class:`Reporter` writing md + json + terminal."""
        from mutagen.reporting import (
            CompositeReporter,
            JsonReporter,
            MarkdownReporter,
            TerminalReporter,
        )

        def build() -> Reporter:
            out = self.config.storage.root / "reports"
            return CompositeReporter.of(
                [
                    MarkdownReporter(out / "report.md"),
                    JsonReporter(out / "report.json"),
                    TerminalReporter(),
                ]
            )

        return self._memo("reporter", build)  # type: ignore[return-value]

    def _database(self) -> _Database:
        """Open (once) the shared SQLite database."""
        from mutagen.infrastructure.store import open_database

        return self._memo(
            "database",
            lambda: open_database(self.config.storage.root / "mutagen.db"),
        )

    def provide_store(self) -> Store:
        """Resolve the configured :class:`Store` (SQLite-backed)."""
        from mutagen.infrastructure.store import SqliteStore

        return self._memo("store", lambda: SqliteStore(self._database()))  # type: ignore[return-value]

    def provide_checkpoint_store(self) -> CheckpointStore:
        """Resolve the configured :class:`CheckpointStore` (SQLite-backed)."""
        from mutagen.infrastructure.store import SqliteCheckpointStore

        return self._memo(
            "checkpoint_store",
            lambda: SqliteCheckpointStore(self._database()),
        )  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # Services
    # ------------------------------------------------------------------ #

    def provide_selection_service(self) -> SelectionService:
        """Resolve the :class:`SelectionService`."""
        return self._memo(
            "selection_service",
            lambda: SelectionService(self.config, self.provide_selector()),
        )  # type: ignore[return-value]

    def provide_reporting_service(self) -> ReportingService:
        """Resolve the :class:`ReportingService`."""
        return self._memo(
            "reporting_service",
            lambda: ReportingService(self.config, self.provide_reporter()),
        )  # type: ignore[return-value]

    def provide_target_processor(self) -> TargetProcessor:
        """Resolve the per-target :class:`TargetProcessor`."""
        return self._memo(
            "target_processor",
            lambda: TargetProcessor(
                config=self.config,
                generator=self.provide_generator(),
                sandbox_runner=self.provide_sandbox_runner(),
                gate=self.provide_gate(),
            ),
        )  # type: ignore[return-value]

    def provide_orchestrator(self) -> PipelineOrchestrator:
        """Resolve the fully-wired :class:`PipelineOrchestrator`."""
        return self._memo(
            "orchestrator",
            lambda: PipelineOrchestrator(
                config=self.config,
                ingestor=self.provide_ingestor(),
                selection_service=self.provide_selection_service(),
                target_processor=self.provide_target_processor(),
                reporting_service=self.provide_reporting_service(),
                reporter=self.provide_reporter(),
                store=self.provide_store(),
                checkpoint_store=self.provide_checkpoint_store(),
            ),
        )  # type: ignore[return-value]
