"""Call-graph domain models.

A :class:`CallGraph` is an immutable, repo-wide map from each function/method to
the functions it calls. It lets the generation pipeline understand a target's
**execution paths** — the tree of helpers a target fans out into — rather than
treating the target as an isolated unit:

.. code-block:: text

    process_order()
     ├── validate_order()
     ├── calculate_tax()
     └── save_order()

Tests informed by that whole tree exercise real end-to-end behaviour instead of
just the top-level function body.

These are pure value objects in the domain layer so the
:class:`mutagen.core.interfaces.CallGraphAnalyzer` port can reference them
without depending on any infrastructure (``ast``, tree-sitter, etc.).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CallSite:
    """A single resolved callee of some function.

    Attributes:
        qualified_name: Dotted name of the callee, relative to its module
            (e.g. ``Class.method`` or ``validate_order``), as resolved within
            the analysed repository. Calls that could not be resolved to a
            known definition are omitted rather than recorded with a guess.
        module_path: Dotted import path of the module defining the callee.
        path: Repo-relative path to the file defining the callee.
        start_line: 1-based line of the callee's ``def``.
        end_line: 1-based last line of the callee's definition.
    """

    qualified_name: str
    module_path: str
    path: Path
    start_line: int
    end_line: int

    @property
    def key(self) -> str:
        """A graph-wide unique key: ``module_path::qualified_name``."""
        return f"{self.module_path}::{self.qualified_name}"


@dataclass(frozen=True, slots=True)
class CallGraph:
    """An immutable map from each function to the functions it calls.

    The graph is keyed by :attr:`CallSite.key` (``module::qualified_name``) so
    that same-named functions in different modules never collide. Only
    intra-repository edges are recorded; calls into third-party libraries or the
    standard library are intentionally excluded — the goal is to surface the
    target's *own* execution path, not the entire transitive world.

    Attributes:
        nodes: Every known function/method, keyed by :attr:`CallSite.key`.
        edges: Adjacency map from a node key to the keys it directly calls.
    """

    nodes: dict[str, CallSite] = field(default_factory=dict)
    edges: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def callees(self, key: str) -> tuple[CallSite, ...]:
        """Return the direct callees of the node identified by ``key``."""
        return tuple(self.nodes[k] for k in self.edges.get(key, ()) if k in self.nodes)

    def transitive_callees(
        self, key: str, *, max_depth: int = 2, max_nodes: int = 12
    ) -> tuple[CallSite, ...]:
        """Return the execution-path subtree reachable from ``key``.

        Performs a breadth-first walk of the call graph starting at ``key``,
        excluding ``key`` itself, bounded by ``max_depth`` hops and ``max_nodes``
        discovered callees so the result stays prompt-sized on deep graphs.
        Recursion and cycles are handled via a visited set. Callees are returned
        in breadth-first (call-order-ish) order, deduplicated.

        Args:
            key: The starting node's key (``module::qualified_name``).
            max_depth: Maximum number of hops away from the start to traverse.
            max_nodes: Cap on the number of callees returned.

        Returns:
            The reachable :class:`CallSite` nodes, nearest-first.
        """
        if key not in self.edges or max_depth <= 0 or max_nodes <= 0:
            return ()
        seen: set[str] = {key}
        out: list[CallSite] = []
        queue: deque[tuple[str, int]] = deque((k, 1) for k in self.edges.get(key, ()))
        while queue and len(out) < max_nodes:
            current, depth = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            node = self.nodes.get(current)
            if node is not None:
                out.append(node)
            if depth < max_depth:
                for child in self.edges.get(current, ()):
                    if child not in seen:
                        queue.append((child, depth + 1))
        return tuple(out[:max_nodes])

    def render_tree(self, key: str, *, max_depth: int = 2) -> str:
        """Render the execution path under ``key`` as an ASCII tree.

        Produces output like::

            process_order
             ├── validate_order
             ├── calculate_tax
             └── save_order

        Returns an empty string if ``key`` is unknown or has no callees.
        """
        root = self.nodes.get(key)
        root_label = root.qualified_name if root else key.split("::", 1)[-1]
        lines: list[str] = [root_label]
        self._render_children(key, prefix="", depth=max_depth, seen={key}, out=lines)
        return "\n".join(lines) if len(lines) > 1 else ""

    def _render_children(
        self,
        key: str,
        *,
        prefix: str,
        depth: int,
        seen: set[str],
        out: list[str],
    ) -> None:
        """Append the rendered children of ``key`` to ``out`` (depth-first)."""
        if depth <= 0:
            return
        children = [k for k in self.edges.get(key, ()) if k in self.nodes]
        for i, child_key in enumerate(children):
            last = i == len(children) - 1
            connector = "└── " if last else "├── "
            node = self.nodes[child_key]
            out.append(f"{prefix}{connector}{node.qualified_name}")
            if child_key not in seen:
                seen.add(child_key)
                extension = "    " if last else "│   "
                self._render_children(
                    child_key,
                    prefix=prefix + extension,
                    depth=depth - 1,
                    seen=seen,
                    out=out,
                )
