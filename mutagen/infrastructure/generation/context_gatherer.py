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
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target

_logger = get_logger(__name__)

# Caps to keep prompts bounded and cache-friendly.
_MAX_EXAMPLE_FILES = 2
_MAX_EXAMPLE_CHARS = 4000
_MAX_CONTEXT_CHARS = 4000


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
    """

    qualified_name: str
    module_path: str
    source: str
    imports: tuple[str, ...] = field(default_factory=tuple)
    surrounding: str = ""
    style_examples: tuple[str, ...] = field(default_factory=tuple)


class ContextGatherer:
    """Assembles source context for a target from the repository snapshot."""

    def __init__(self, config: RunConfig) -> None:
        self._config = config

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
        examples = self._gather_examples(context)
        return GatheredContext(
            qualified_name=target.qualified_name,
            module_path=module_path,
            source=source,
            imports=imports,
            surrounding=surrounding,
            style_examples=examples,
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

    def _gather_examples(self, context: RepoContext) -> tuple[str, ...]:
        """Read a couple of existing test modules as style examples."""
        examples: list[str] = []
        for rel in context.test_files[:_MAX_EXAMPLE_FILES]:
            text = self._read(context.root / rel)
            if text.strip():
                examples.append(self._trim(text, _MAX_EXAMPLE_CHARS))
        return tuple(examples)

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
