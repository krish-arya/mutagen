"""Tests for call-graph analysis and the :class:`CallGraph` model.

Cover edge resolution (plain calls, ``self`` methods, cross-module imports),
the conservative omission of unresolvable/third-party calls, the bounded
transitive walk (depth, count, cycles), and the ASCII tree rendering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.core.models.call_graph import CallGraph, CallSite
from mutagen.core.models.repo import RepoContext
from mutagen.infrastructure.selection import AstCallGraphAnalyzer


def _context(tmp_path: Path, files: dict[str, str]) -> RepoContext:
    """Write ``files`` (rel path -> source) under ``tmp_path`` and snapshot."""
    sources = []
    for rel, src in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
        sources.append(Path(rel))
    return RepoContext(root=tmp_path.resolve(), source_files=tuple(sources))


@pytest.fixture
def analyzer() -> AstCallGraphAnalyzer:
    return AstCallGraphAnalyzer()


# --------------------------------------------------------------------------- #
# Edge resolution
# --------------------------------------------------------------------------- #


def test_resolves_same_module_calls(
    analyzer: AstCallGraphAnalyzer, tmp_path: Path
) -> None:
    src = (
        "def validate_order(o): return True\n"
        "def calculate_tax(o): return o * 0.1\n"
        "def save_order(o): return o\n"
        "def process_order(o):\n"
        "    validate_order(o)\n"
        "    t = calculate_tax(o)\n"
        "    return save_order(o + t)\n"
    )
    graph = analyzer.analyze(_context(tmp_path, {"orders.py": src}))
    callees = {c.qualified_name for c in graph.callees("orders::process_order")}
    assert callees == {"validate_order", "calculate_tax", "save_order"}


def test_resolves_self_method_calls(
    analyzer: AstCallGraphAnalyzer, tmp_path: Path
) -> None:
    src = (
        "class Service:\n"
        "    def save(self): return 1\n"
        "    def run(self):\n"
        "        return self.save()\n"
    )
    graph = analyzer.analyze(_context(tmp_path, {"svc.py": src}))
    callees = {c.qualified_name for c in graph.callees("svc::Service.run")}
    assert callees == {"Service.save"}


def test_resolves_cross_module_import(
    analyzer: AstCallGraphAnalyzer, tmp_path: Path
) -> None:
    helpers = "def helper(x): return x\n"
    main = "from helpers import helper\ndef run():\n    return helper(1)\n"
    graph = analyzer.analyze(
        _context(tmp_path, {"helpers.py": helpers, "main.py": main})
    )
    callees = {c.module_path for c in graph.callees("main::run")}
    assert "helpers" in callees


def test_ignores_third_party_and_unresolved_calls(
    analyzer: AstCallGraphAnalyzer, tmp_path: Path
) -> None:
    src = "import os\ndef run():\n    os.getcwd()\n    undefined_func()\n    return 1\n"
    graph = analyzer.analyze(_context(tmp_path, {"m.py": src}))
    # No in-repo callees: ``os.getcwd`` and the undefined name are both omitted.
    assert graph.callees("m::run") == ()


def test_does_not_record_self_edge_for_recursion(
    analyzer: AstCallGraphAnalyzer, tmp_path: Path
) -> None:
    src = "def fact(n):\n    return 1 if n <= 1 else n * fact(n - 1)\n"
    graph = analyzer.analyze(_context(tmp_path, {"m.py": src}))
    assert graph.callees("m::fact") == ()


def test_skips_unparsable_files(analyzer: AstCallGraphAnalyzer, tmp_path: Path) -> None:
    good = "def f(): return g()\ndef g(): return 1\n"
    bad = "def broken(:\n"
    graph = analyzer.analyze(_context(tmp_path, {"good.py": good, "bad.py": bad}))
    assert "good::f" in graph.nodes
    assert {c.qualified_name for c in graph.callees("good::f")} == {"g"}


# --------------------------------------------------------------------------- #
# CallGraph model: traversal + rendering
# --------------------------------------------------------------------------- #


def _site(name: str) -> CallSite:
    return CallSite(
        qualified_name=name,
        module_path="m",
        path=Path("m.py"),
        start_line=1,
        end_line=2,
    )


def _graph(edges: dict[str, tuple[str, ...]]) -> CallGraph:
    names = set(edges) | {c for cs in edges.values() for c in cs}
    nodes = {n: _site(n.split("::")[-1]) for n in names}
    return CallGraph(nodes=nodes, edges=edges)


def test_transitive_callees_respects_depth() -> None:
    graph = _graph({"a": ("b",), "b": ("c",), "c": ("d",)})
    one = {s.qualified_name for s in graph.transitive_callees("a", max_depth=1)}
    two = {s.qualified_name for s in graph.transitive_callees("a", max_depth=2)}
    assert one == {"b"}
    assert two == {"b", "c"}


def test_transitive_callees_respects_max_nodes() -> None:
    graph = _graph({"a": ("b", "c", "d")})
    result = graph.transitive_callees("a", max_depth=3, max_nodes=2)
    assert len(result) == 2


def test_transitive_callees_handles_cycles() -> None:
    graph = _graph({"a": ("b",), "b": ("a",)})
    # Must terminate and not revisit the start.
    names = {s.qualified_name for s in graph.transitive_callees("a", max_depth=5)}
    assert names == {"b"}


def test_render_tree_shapes_branches() -> None:
    graph = _graph({"a": ("b", "c")})
    tree = graph.render_tree("a")
    lines = tree.splitlines()
    assert lines[0] == "a"
    assert lines[1].endswith("b") and "├──" in lines[1]
    assert lines[2].endswith("c") and "└──" in lines[2]


def test_render_tree_empty_when_no_callees() -> None:
    graph = _graph({"a": ()})
    assert graph.render_tree("a") == ""
