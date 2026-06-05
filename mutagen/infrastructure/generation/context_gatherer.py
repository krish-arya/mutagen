"""Gathering source context for test generation.

:class:`ContextGatherer` assembles everything the prompt needs about a target,
reading from the on-disk repository snapshot:

1. **Function source** — the exact lines defining the target.
2. **Imports** — the module's import statements, so the model knows what is in
   scope.
3. **Surrounding context** — sibling definitions and module-level assignments
   that the target may depend on, trimmed to a budget.
4. **Existing test examples** — snippets of the project's own tests, so the
   generated test matches local style.

It performs only reads and AST parsing — no LLM calls, no writes — which keeps
it cheap and fully testable against fixtures.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import RunConfig
from mutagen.core.interfaces import CallGraphAnalyzer, TestRetriever
from mutagen.core.models.call_graph import CallGraph, CallSite
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.retrieval import RetrievalQuery
from mutagen.core.models.target import Target

_logger = get_logger(__name__)

# Caps to keep prompts bounded and cache-friendly.
_MAX_EXAMPLE_FILES = 2
_MAX_EXAMPLE_CHARS = 4000
_MAX_CONTEXT_CHARS = 4000
_MAX_CALLEE_CHARS = 3000


@dataclass(frozen=True, slots=True)
class GatheredContext:
    """The assembled source context for one target.

    Attributes:
        qualified_name: Dotted import path to the target symbol.
        module_path: Dotted import path of the module defining the target.
        source: The exact source lines of the target definition.
        imports: Import statements from the target's module, as source lines.
        surrounding: Trimmed sibling/module-level source the target may rely on.
        style_examples: Snippets of existing project tests, for style matching.
        call_tree: ASCII rendering of the target's execution path (its
            transitive callees), or empty when call-graph context is disabled
            or the target calls nothing in-repo.
        callee_sources: Source snippets of the target's transitive callees, so
            the model can write tests that exercise the whole execution path.
    """

    qualified_name: str
    module_path: str
    source: str
    imports: tuple[str, ...] = field(default_factory=tuple)
    surrounding: str = ""
    style_examples: tuple[str, ...] = field(default_factory=tuple)
    call_tree: str = ""
    callee_sources: tuple[str, ...] = field(default_factory=tuple)


class ContextGatherer:
    """Assembles source context for a target from the repository snapshot.

    Two optional collaborators enrich the context when configured:

    * ``call_graph_analyzer`` adds *semantic* understanding — the target's
      execution path (its transitive callees), gathered once per run and cached.
    * ``retriever`` adds *retrieval-augmented* style examples — the existing
      tests most similar to the target, rather than the first couple of files.

    Both are optional; when absent the gatherer behaves exactly as before.
    """

    def __init__(
        self,
        config: RunConfig,
        call_graph_analyzer: CallGraphAnalyzer | None = None,
        retriever: TestRetriever | None = None,
    ) -> None:
        self._config = config
        self._call_graph_analyzer = call_graph_analyzer
        self._retriever = retriever
        # Lazily built per run, keyed by repo root so a reused gatherer across
        # repos never serves a stale graph/index.
        self._graph: CallGraph | None = None
        self._graph_root: Path | None = None
        self._indexed_root: Path | None = None

    def gather(self, target: Target, context: RepoContext) -> GatheredContext:
        """Gather all source context for ``target``.

        Args:
            target: The target to gather context for.
            context: The ingested repository snapshot.

        Returns:
            A :class:`GatheredContext` ready to feed the prompt builder.
        """
        module_path = self._module_qualname(target.span.path)
        module_source = self._read(context.root / target.span.path)
        source = self._extract_target_source(module_source, target)
        imports = self._extract_imports(module_source)
        surrounding = self._extract_surrounding(module_source, target)
        examples = self._gather_examples(target, context)
        call_tree, callee_sources = self._gather_call_graph(target, context)
        return GatheredContext(
            qualified_name=target.qualified_name,
            module_path=module_path,
            source=source,
            imports=imports,
            surrounding=surrounding,
            style_examples=examples,
            call_tree=call_tree,
            callee_sources=callee_sources,
        )

    def _symbol(self, target: Target, module_path: str) -> str:
        """The target's symbol relative to its module (strip module prefix)."""
        qualified = target.qualified_name
        prefix = f"{module_path}."
        if qualified.startswith(prefix):
            return qualified[len(prefix) :]
        return qualified.rsplit(".", 1)[-1]

    # ------------------------------------------------------------------ #
    # Requirement 1: function source
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_target_source(module_source: str, target: Target) -> str:
        """Return the source lines spanning the target definition."""
        lines = module_source.splitlines()
        start = max(0, target.span.start_line - 1)
        end = min(len(lines), target.span.end_line)
        return "\n".join(lines[start:end])

    # ------------------------------------------------------------------ #
    # Requirement 2: imports
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_imports(module_source: str) -> tuple[str, ...]:
        """Return the module-level import statements as source lines."""
        try:
            tree = ast.parse(module_source)
        except SyntaxError:
            return ()
        lines = module_source.splitlines()
        imports: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                segment = ast.get_source_segment(module_source, node)
                if segment is not None:
                    imports.append(segment)
                elif 1 <= node.lineno <= len(lines):
                    imports.append(lines[node.lineno - 1])
        return tuple(imports)

    # ------------------------------------------------------------------ #
    # Requirement 3: surrounding context
    # ------------------------------------------------------------------ #

    def _extract_surrounding(self, module_source: str, target: Target) -> str:
        """Return sibling defs and module-level assignments, trimmed to budget.

        Excludes the target's own source (already gathered) and import lines
        (gathered separately).
        """
        try:
            tree = ast.parse(module_source)
        except SyntaxError:
            return ""
        module_path = self._module_qualname(target.span.path)
        symbol = self._symbol(target, module_path)
        chunks: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if self._defines_symbol(node, symbol):
                continue
            if isinstance(node, ast.Assign):
                segment = ast.get_source_segment(module_source, node)
                if segment is not None:
                    chunks.append(segment)
            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                chunks.append(self._signature_only(module_source, node))
        return self._trim("\n\n".join(c for c in chunks if c), _MAX_CONTEXT_CHARS)

    @staticmethod
    def _defines_symbol(node: ast.stmt, symbol: str) -> bool:
        """Whether a top-level node defines the (possibly dotted) target."""
        top = symbol.split(".", 1)[0]
        name = getattr(node, "name", None)
        return name == top

    @staticmethod
    def _signature_only(module_source: str, node: ast.AST) -> str:
        """Return just the signature line(s) of a def/class, not its body."""
        segment = ast.get_source_segment(module_source, node)
        if segment is None:
            return ""
        # Keep up to the first line ending in a colon (the signature header).
        out: list[str] = []
        for line in segment.splitlines():
            out.append(line)
            if line.rstrip().endswith(":"):
                break
        return "\n".join(out)

    # ------------------------------------------------------------------ #
    # Requirement 4: existing test examples
    # ------------------------------------------------------------------ #

    def _gather_examples(self, target: Target, context: RepoContext) -> tuple[str, ...]:
        """Gather existing-test style examples.

        When retrieval is enabled and a retriever is wired, return the existing
        tests most *similar* to the target (RAG); otherwise fall back to reading
        the first couple of test modules.
        """
        retrieved = self._retrieve_examples(target, context)
        if retrieved is not None:
            return retrieved
        examples: list[str] = []
        for rel in context.test_files[:_MAX_EXAMPLE_FILES]:
            text = self._read(context.root / rel)
            if text.strip():
                examples.append(self._trim(text, _MAX_EXAMPLE_CHARS))
        return tuple(examples)

    def _retrieve_examples(
        self, target: Target, context: RepoContext
    ) -> tuple[str, ...] | None:
        """Return retrieval-ranked examples, or ``None`` if retrieval is off.

        Returns an empty tuple (not ``None``) if retrieval ran but found
        nothing, so the caller does not silently fall back to the heuristic.
        """
        if not self._config.generation.use_retrieval or self._retriever is None:
            return None
        self._ensure_index(context)
        query = RetrievalQuery(
            text=f"{target.qualified_name}\n{target.signature}",
            top_k=self._config.generation.retrieval_top_k,
            kinds=("test",),
        )
        results = self._retriever.retrieve(query)
        return tuple(
            self._trim(example.document.text, _MAX_EXAMPLE_CHARS) for example in results
        )

    def _ensure_index(self, context: RepoContext) -> None:
        """Build the retrieval index once per repository snapshot."""
        if self._retriever is None or self._indexed_root == context.root:
            return
        from mutagen.infrastructure.retrieval import CorpusIndexer

        documents = CorpusIndexer().build(context)
        self._retriever.index(documents)
        self._indexed_root = context.root
        _logger.info(
            "retrieval index built",
            extra={"context": {"documents": len(documents)}},
        )

    # ------------------------------------------------------------------ #
    # Semantic call-graph context (execution path)
    # ------------------------------------------------------------------ #

    def _gather_call_graph(
        self, target: Target, context: RepoContext
    ) -> tuple[str, tuple[str, ...]]:
        """Return ``(call_tree, callee_sources)`` for the target's execution path.

        Builds the repo call graph once (cached per snapshot), locates the
        target node, and renders both an ASCII tree and the source of each
        transitive callee, bounded by the configured depth/count caps. Returns
        empties when call-graph context is disabled or the target is unknown.
        """
        gen = self._config.generation
        if not gen.use_call_graph or self._call_graph_analyzer is None:
            return "", ()
        graph = self._ensure_graph(context)
        key = self._target_key(target)
        if key is None:
            return "", ()
        tree = graph.render_tree(key, max_depth=gen.call_graph_max_depth)
        callees = graph.transitive_callees(
            key,
            max_depth=gen.call_graph_max_depth,
            max_nodes=gen.call_graph_max_callees,
        )
        sources = self._render_callee_sources(callees, context)
        return tree, sources

    def _ensure_graph(self, context: RepoContext) -> CallGraph:
        """Build (and cache) the repository call graph for this snapshot."""
        assert self._call_graph_analyzer is not None
        if self._graph is None or self._graph_root != context.root:
            self._graph = self._call_graph_analyzer.analyze(context)
            self._graph_root = context.root
        return self._graph

    def _target_key(self, target: Target) -> str | None:
        """Resolve a target to its call-graph node key, if present."""
        graph = self._graph
        if graph is None:
            return None
        module_path = self._module_qualname(target.span.path)
        symbol = self._symbol(target, module_path)
        candidate = f"{module_path}::{symbol}"
        if candidate in graph.nodes:
            return candidate
        # Fall back to a node whose path+line span matches the target def.
        for key, site in graph.nodes.items():
            if (
                site.path == target.span.path
                and site.start_line == target.span.start_line
            ):
                return key
        return None

    def _render_callee_sources(
        self, callees: tuple[CallSite, ...], context: RepoContext
    ) -> tuple[str, ...]:
        """Read and label the source of each callee, trimmed to a budget."""
        snippets: list[str] = []
        for site in callees:
            module_source = self._read(context.root / site.path)
            if not module_source:
                continue
            lines = module_source.splitlines()
            start = max(0, site.start_line - 1)
            end = min(len(lines), site.end_line)
            body = "\n".join(lines[start:end])
            if body.strip():
                snippets.append(f"# {site.qualified_name}\n{body}")
        joined = "\n\n".join(snippets)
        if len(joined) <= _MAX_CALLEE_CHARS:
            return tuple(snippets)
        # Drop trailing snippets until under budget rather than mid-cutting one.
        bounded: list[str] = []
        used = 0
        for snippet in snippets:
            if used + len(snippet) > _MAX_CALLEE_CHARS:
                break
            bounded.append(snippet)
            used += len(snippet)
        return tuple(bounded)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _module_qualname(rel_path: Path) -> str:
        """Convert a repo-relative ``.py`` path to a dotted module name."""
        return ".".join(rel_path.with_suffix("").parts)

    @staticmethod
    def _read(path: Path) -> str:
        """Read a file, returning empty string if it cannot be read."""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            _logger.warning(
                "could not read source for context",
                extra={"context": {"path": str(path), "error": str(exc)}},
            )
            return ""

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        """Truncate ``text`` to ``limit`` characters with an ellipsis marker."""
        if len(text) <= limit:
            return text
        return text[:limit] + "\n# ... (truncated)"
