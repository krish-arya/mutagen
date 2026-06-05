"""Call-graph analysis via the :mod:`ast` module.

:class:`AstCallGraphAnalyzer` walks every source file in a
:class:`RepoContext`, records each function/method definition as a graph node,
and resolves the calls inside each body to other definitions in the same
repository — producing a :class:`CallGraph` the generation pipeline uses to
understand a target's full execution path.

Resolution is deliberately conservative. Python is dynamically typed, so a
perfectly precise call graph is undecidable; this analyzer resolves the cases
that are both common and unambiguous and *omits* anything it cannot pin down,
rather than recording a misleading edge:

* plain calls — ``validate_order()`` → a same-module or repo-wide function of
  that name;
* attribute calls on ``self``/``cls`` — ``self.save()`` → a method named
  ``save`` on the enclosing class;
* module-qualified calls — ``orders.calculate_tax()`` where ``orders`` was
  imported from a repo module.

It uses only the standard library. ``ast`` gives exact line spans and is
sufficient for Python sources; a tree-sitter backend (for polyglot repos) can
implement the same :class:`CallGraphAnalyzer` port without touching callers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.core.interfaces import CallGraphAnalyzer
from mutagen.core.models.call_graph import CallGraph, CallSite
from mutagen.core.models.repo import RepoContext

_logger = get_logger(__name__)


@dataclass(slots=True)
class _Definition:
    """A function/method definition discovered while indexing a module."""

    qualified_name: str
    module_path: str
    path: Path
    start_line: int
    end_line: int
    enclosing_class: str | None
    calls: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.module_path}::{self.qualified_name}"

    def to_site(self) -> CallSite:
        return CallSite(
            qualified_name=self.qualified_name,
            module_path=self.module_path,
            path=self.path,
            start_line=self.start_line,
            end_line=self.end_line,
        )


class AstCallGraphAnalyzer(CallGraphAnalyzer):
    """Builds a repository call graph from Python source using ``ast``."""

    def analyze(self, context: RepoContext) -> CallGraph:
        """Build a :class:`CallGraph` over ``context``'s source files."""
        definitions: list[_Definition] = []
        # Imports of repo modules, per file: local alias -> module dotted path.
        module_aliases: dict[str, dict[str, str]] = {}
        known_modules = {self._module_qualname(p) for p in context.source_files}

        for rel in context.source_files:
            source = self._read(context.root / rel)
            if not source:
                continue
            try:
                tree = ast.parse(source, filename=str(rel))
            except SyntaxError as exc:
                _logger.warning(
                    "skipping unparsable file in call-graph analysis",
                    extra={"context": {"path": str(rel), "error": str(exc)}},
                )
                continue
            module_path = self._module_qualname(rel)
            module_aliases[module_path] = self._import_aliases(tree, known_modules)
            self._collect_definitions(tree, rel, module_path, out=definitions)

        return self._build_graph(definitions, module_aliases)

    # ------------------------------------------------------------------ #
    # Indexing
    # ------------------------------------------------------------------ #

    def _collect_definitions(
        self,
        tree: ast.Module,
        rel: Path,
        module_path: str,
        *,
        out: list[_Definition],
    ) -> None:
        """Record every def/method in ``tree`` with the calls in its body."""
        self._visit(tree.body, rel, module_path, prefix="", cls=None, out=out)

    def _visit(
        self,
        body: list[ast.stmt],
        rel: Path,
        module_path: str,
        *,
        prefix: str,
        cls: str | None,
        out: list[_Definition],
    ) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}{node.name}" if prefix else node.name
                out.append(
                    _Definition(
                        qualified_name=qualified,
                        module_path=module_path,
                        path=rel,
                        start_line=node.lineno,
                        end_line=self._end_line(node),
                        enclosing_class=cls,
                        calls=self._extract_calls(node),
                    )
                )
                # Descend into nested defs (keep class context off for locals).
                self._visit(
                    node.body,
                    rel,
                    module_path,
                    prefix=f"{qualified}.<locals>.",
                    cls=None,
                    out=out,
                )
            elif isinstance(node, ast.ClassDef):
                qualified = f"{prefix}{node.name}." if prefix else f"{node.name}."
                self._visit(
                    node.body,
                    rel,
                    module_path,
                    prefix=qualified,
                    cls=node.name,
                    out=out,
                )

    @staticmethod
    def _extract_calls(node: ast.AST) -> tuple[str, ...]:
        """Return raw, unresolved call references inside a definition body.

        Each reference is encoded so the resolver can interpret it:

        * ``"name"`` — a bare call ``name(...)``;
        * ``"self.attr"`` / ``"cls.attr"`` — a method call on the instance/class;
        * ``"alias.attr"`` — an attribute call on some other name.

        Nested-function bodies are excluded (they are their own nodes).
        """
        calls: list[str] = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                base = func.value
                if isinstance(base, ast.Name):
                    calls.append(f"{base.id}.{func.attr}")
        # Stable de-dup preserving first-seen order.
        seen: set[str] = set()
        ordered: list[str] = []
        for c in calls:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
        return tuple(ordered)

    @staticmethod
    def _import_aliases(tree: ast.Module, known_modules: set[str]) -> dict[str, str]:
        """Map local names to repo module paths for ``import``/``from`` forms.

        Only repo-internal modules (present in ``known_modules``) are tracked;
        third-party imports are ignored so they never produce spurious edges.
        """
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name in known_modules:
                        aliases[name.asname or name.name.split(".")[0]] = name.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in known_modules:
                    # ``from pkg.mod import name`` — ``name`` resolves into mod.
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = node.module
        return aliases

    # ------------------------------------------------------------------ #
    # Resolution
    # ------------------------------------------------------------------ #

    def _build_graph(
        self,
        definitions: list[_Definition],
        module_aliases: dict[str, dict[str, str]],
    ) -> CallGraph:
        """Resolve every definition's calls into concrete edges."""
        nodes: dict[str, CallSite] = {d.key: d.to_site() for d in definitions}
        # Indexes for resolution.
        by_simple_name: dict[str, list[_Definition]] = {}
        by_module_and_name: dict[tuple[str, str], _Definition] = {}
        methods_by_class: dict[tuple[str, str], _Definition] = {}
        for d in definitions:
            simple = d.qualified_name.rsplit(".", 1)[-1]
            by_simple_name.setdefault(simple, []).append(d)
            by_module_and_name[(d.module_path, d.qualified_name)] = d
            if d.enclosing_class is not None:
                methods_by_class[(d.module_path, simple)] = d

        edges: dict[str, tuple[str, ...]] = {}
        for d in definitions:
            resolved: list[str] = []
            aliases = module_aliases.get(d.module_path, {})
            for ref in d.calls:
                target = self._resolve(
                    ref,
                    caller=d,
                    aliases=aliases,
                    by_simple_name=by_simple_name,
                    by_module_and_name=by_module_and_name,
                    methods_by_class=methods_by_class,
                )
                if target is not None and target.key != d.key:
                    resolved.append(target.key)
            # De-dup while preserving order.
            seen: set[str] = set()
            ordered = [k for k in resolved if not (k in seen or seen.add(k))]
            if ordered:
                edges[d.key] = tuple(ordered)
        return CallGraph(nodes=nodes, edges=edges)

    def _resolve(
        self,
        ref: str,
        *,
        caller: _Definition,
        aliases: dict[str, str],
        by_simple_name: dict[str, list[_Definition]],
        by_module_and_name: dict[tuple[str, str], _Definition],
        methods_by_class: dict[tuple[str, str], _Definition],
    ) -> _Definition | None:
        """Resolve a single call reference to a known definition, or ``None``."""
        if "." not in ref:
            return self._resolve_simple(ref, caller, by_simple_name)

        base, attr = ref.split(".", 1)
        if base in {"self", "cls"} and caller.enclosing_class is not None:
            # Method call on the enclosing class.
            return methods_by_class.get((caller.module_path, attr))
        if base in aliases:
            module = aliases[base]
            # ``from mod import name`` style: alias maps to the module, attr is
            # the called symbol; for ``import mod`` the symbol is ``attr`` too.
            hit = by_module_and_name.get((module, attr))
            if hit is not None:
                return hit
            # ``from mod import func; func()`` is handled by the simple path;
            # here ``base`` itself may be the imported symbol.
        # ``from mod import symbol`` then ``symbol.method()`` is out of scope.
        return None

    @staticmethod
    def _resolve_simple(
        name: str,
        caller: _Definition,
        by_simple_name: dict[str, list[_Definition]],
    ) -> _Definition | None:
        """Resolve a bare ``name()`` call, preferring same-module definitions."""
        candidates = by_simple_name.get(name)
        if not candidates:
            return None
        # Prefer a same-module, top-level (non-method) definition.
        same_module = [
            c
            for c in candidates
            if c.module_path == caller.module_path and c.enclosing_class is None
        ]
        if same_module:
            return same_module[0]
        # Fall back to a unique repo-wide free function of that name.
        free = [c for c in candidates if c.enclosing_class is None]
        if len(free) == 1:
            return free[0]
        return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _end_line(node: ast.AST) -> int:
        end = getattr(node, "end_lineno", None)
        if end is not None:
            return int(end)
        return max(
            (getattr(child, "lineno", 0) for child in ast.walk(node)),
            default=getattr(node, "lineno", 0),
        )

    @staticmethod
    def _module_qualname(rel_path: Path) -> str:
        return ".".join(rel_path.with_suffix("").parts)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
