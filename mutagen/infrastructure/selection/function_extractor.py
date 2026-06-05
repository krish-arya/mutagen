"""Function extraction via the :mod:`ast` module.

:class:`FunctionExtractor` parses a Python source file and yields one
:class:`ExtractedFunction` per function or method definition, capturing the
facts the ranker needs: fully-qualified name, kind, line span, the set of
executable body lines, decorators, and a statement count used by the
trivial/giant filters.

Extraction is pure with respect to the filesystem beyond reading the source
text; it performs no coverage measurement and makes no ranking decisions.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.core.exceptions import MutagenError
from mutagen.core.models.target import TargetKind

_logger = get_logger(__name__)


class ExtractionError(MutagenError):
    """Raised when a source file cannot be parsed into functions."""


@dataclass(frozen=True, slots=True)
class ExtractedFunction:
    """A function or method discovered in a source file.

    Attributes:
        qualified_name: Dotted name relative to the module, including any
            enclosing classes/functions (e.g. ``Class.method``,
            ``outer.<locals>.inner``).
        kind: Whether the definition is a free function or a method.
        start_line: 1-based line of the ``def``/``async def`` (after
            decorators, matching ``coverage.py`` line semantics for the body).
        end_line: 1-based last line of the definition.
        body_lines: Executable line numbers belonging to the body, excluding
            the signature, decorators, and docstring.
        statement_count: Number of statements in the body (recursively),
            used to classify trivial vs. giant functions.
        decorators: Decorator names applied to the definition, in source
            order (e.g. ``("property",)``).
        is_async: Whether the definition is ``async def``.
    """

    qualified_name: str
    kind: TargetKind
    start_line: int
    end_line: int
    body_lines: frozenset[int] = field(default_factory=frozenset)
    statement_count: int = 0
    decorators: tuple[str, ...] = field(default_factory=tuple)
    is_async: bool = False

    @property
    def is_property(self) -> bool:
        """Whether this looks like a ``@property`` (or related) accessor."""
        return any(
            d in {"property", "cached_property", "functools.cached_property"}
            for d in self.decorators
        )


class FunctionExtractor:
    """Extracts function/method definitions from Python source files."""

    def extract_source(
        self, source: str, *, filename: str = "<unknown>"
    ) -> list[ExtractedFunction]:
        """Extract functions from in-memory ``source`` text.

        Args:
            source: The Python source to parse.
            filename: Name used in syntax-error messages.

        Returns:
            A list of :class:`ExtractedFunction`, in source order.

        Raises:
            ExtractionError: If ``source`` is not valid Python.
        """
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            raise ExtractionError(f"Failed to parse {filename}: {exc}") from exc

        functions: list[ExtractedFunction] = []
        self._visit_body(tree.body, prefix="", out=functions)
        return functions

    def extract_file(self, path: Path) -> list[ExtractedFunction]:
        """Extract functions from the file at ``path``.

        Args:
            path: Filesystem path to a Python source file.

        Returns:
            A list of :class:`ExtractedFunction`, in source order.

        Raises:
            ExtractionError: If the file cannot be read or parsed.
        """
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ExtractionError(f"Failed to read {path}: {exc}") from exc
        return self.extract_source(source, filename=str(path))

    def _visit_body(
        self,
        body: list[ast.stmt],
        *,
        prefix: str,
        out: list[ExtractedFunction],
        in_class: bool = False,
    ) -> None:
        """Recurse through a block, recording defs and descending into nests."""
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}{node.name}" if prefix else node.name
                out.append(self._build(node, qualified, in_class=in_class))
                # Nested functions live under ``<name>.<locals>.``.
                self._visit_body(
                    node.body,
                    prefix=f"{qualified}.<locals>.",
                    out=out,
                    in_class=False,
                )
            elif isinstance(node, ast.ClassDef):
                qualified = f"{prefix}{node.name}." if prefix else f"{node.name}."
                self._visit_body(node.body, prefix=qualified, out=out, in_class=True)

    def _build(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        qualified_name: str,
        *,
        in_class: bool,
    ) -> ExtractedFunction:
        """Construct an :class:`ExtractedFunction` from a def node."""
        body_lines = self._body_lines(node)
        return ExtractedFunction(
            qualified_name=qualified_name,
            kind=TargetKind.METHOD if in_class else TargetKind.FUNCTION,
            start_line=node.lineno,
            end_line=self._end_line(node),
            body_lines=frozenset(body_lines),
            statement_count=self._statement_count(node),
            decorators=tuple(self._decorator_name(d) for d in node.decorator_list),
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )

    @staticmethod
    def _end_line(node: ast.AST) -> int:
        """Best-effort last line of a node (``end_lineno`` since 3.8)."""
        end = getattr(node, "end_lineno", None)
        if end is not None:
            return end
        return max(
            (getattr(child, "lineno", 0) for child in ast.walk(node)),
            default=getattr(node, "lineno", 0),
        )

    @classmethod
    def _body_lines(cls, node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
        """Return executable body line numbers, skipping a leading docstring."""
        body = list(node.body)
        if body and cls._is_docstring(body[0]):
            body = body[1:]
        lines: set[int] = set()
        for stmt in body:
            for child in ast.walk(stmt):
                lineno = getattr(child, "lineno", None)
                if isinstance(lineno, int):
                    lines.add(lineno)
        return lines

    @classmethod
    def _statement_count(cls, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """Count statements in the body, excluding a leading docstring."""
        body = list(node.body)
        if body and cls._is_docstring(body[0]):
            body = body[1:]
        count = 0
        for stmt in body:
            for child in ast.walk(stmt):
                if isinstance(child, ast.stmt):
                    count += 1
        return count

    @staticmethod
    def _is_docstring(stmt: ast.stmt) -> bool:
        """Whether ``stmt`` is a bare string-constant expression (docstring)."""
        return (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )

    @classmethod
    def _decorator_name(cls, node: ast.expr) -> str:
        """Render a decorator expression to a dotted name."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{cls._decorator_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return cls._decorator_name(node.func)
        return ""
