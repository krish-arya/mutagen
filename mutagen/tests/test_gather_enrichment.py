"""Tests for :class:`ContextGatherer`'s optional enrichment.

Verify that call-graph (semantic execution-path) context and
retrieval-augmented examples are folded in when enabled, are absent when
disabled, and that the enriched context reaches the generation prompt.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from mutagen.config.run_config import GenerationConfig, RunConfig
from mutagen.core.models.location import SourceSpan
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.target import Target, TargetKind
from mutagen.infrastructure.generation import ContextGatherer
from mutagen.infrastructure.retrieval import (
    EmbeddingTestRetriever,
    HashingEmbeddingProvider,
)
from mutagen.infrastructure.selection import AstCallGraphAnalyzer


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> RepoContext:
    _write(
        tmp_path / "orders.py",
        "def validate_order(o):\n    return o is not None\n"
        "def calculate_tax(o):\n    return o * 0.1\n"
        "def save_order(o):\n    return o\n"
        "def process_order(o):\n"
        "    validate_order(o)\n"
        "    t = calculate_tax(o)\n"
        "    return save_order(o + t)\n",
    )
    _write(
        tmp_path / "tests" / "test_orders.py",
        "def test_calculate_tax():\n    assert calculate_tax(100) == 10\n\n"
        "def test_login_flow():\n    assert authenticate(user) is True\n",
    )
    return RepoContext(
        root=tmp_path.resolve(),
        source_files=(Path("orders.py"),),
        test_files=(Path("tests/test_orders.py"),),
        python_version="3.11",
    )


def _target() -> Target:
    return Target(
        target_id="t1",
        qualified_name="orders.process_order",
        kind=TargetKind.FUNCTION,
        span=SourceSpan(path=Path("orders.py"), start_line=7, end_line=10),
    )


def _config(tmp_path: Path, generation: GenerationConfig) -> RunConfig:
    return RunConfig(project_root=tmp_path, generation=generation)


# --------------------------------------------------------------------------- #
# Call-graph enrichment
# --------------------------------------------------------------------------- #


def test_call_graph_disabled_by_default(repo: RepoContext, tmp_path: Path) -> None:
    gatherer = ContextGatherer(
        RunConfig(project_root=tmp_path),
        call_graph_analyzer=AstCallGraphAnalyzer(),
    )
    gathered = gatherer.gather(_target(), repo)
    assert gathered.call_tree == ""
    assert gathered.callee_sources == ()


def test_call_graph_adds_execution_path(repo: RepoContext, tmp_path: Path) -> None:
    config = _config(tmp_path, GenerationConfig(use_call_graph=True))
    gatherer = ContextGatherer(config, call_graph_analyzer=AstCallGraphAnalyzer())
    gathered = gatherer.gather(_target(), repo)
    assert "validate_order" in gathered.call_tree
    assert "calculate_tax" in gathered.call_tree
    joined = "\n".join(gathered.callee_sources)
    assert "return o * 0.1" in joined  # calculate_tax body is included


def test_call_graph_noop_without_analyzer(repo: RepoContext, tmp_path: Path) -> None:
    config = _config(tmp_path, GenerationConfig(use_call_graph=True))
    gathered = ContextGatherer(config).gather(_target(), repo)
    assert gathered.call_tree == ""


# --------------------------------------------------------------------------- #
# Retrieval enrichment
# --------------------------------------------------------------------------- #


def _retriever() -> EmbeddingTestRetriever:
    return EmbeddingTestRetriever(HashingEmbeddingProvider(dim=512))


def test_retrieval_disabled_uses_first_files(repo: RepoContext, tmp_path: Path) -> None:
    gatherer = ContextGatherer(RunConfig(project_root=tmp_path), retriever=_retriever())
    gathered = gatherer.gather(_target(), repo)
    # Heuristic path: whole file, so both test functions appear in one example.
    assert any("test_login_flow" in ex for ex in gathered.style_examples)


def test_retrieval_surfaces_similar_test(repo: RepoContext, tmp_path: Path) -> None:
    config = _config(tmp_path, GenerationConfig(use_retrieval=True, retrieval_top_k=1))
    target = dataclasses.replace(
        _target(), qualified_name="orders.calculate_tax", signature="calculate_tax(o)"
    )
    gathered = ContextGatherer(config, retriever=_retriever()).gather(target, repo)
    assert len(gathered.style_examples) == 1
    # The tax test is more similar than the login test.
    assert "calculate_tax" in gathered.style_examples[0]
    assert "test_login_flow" not in gathered.style_examples[0]


def test_index_built_once_across_targets(repo: RepoContext, tmp_path: Path) -> None:
    config = _config(tmp_path, GenerationConfig(use_retrieval=True))
    retriever = _retriever()
    calls: list[int] = []
    original = retriever.index

    def counting_index(docs):  # type: ignore[no-untyped-def]
        calls.append(len(docs))
        original(docs)

    retriever.index = counting_index  # type: ignore[method-assign]
    gatherer = ContextGatherer(config, retriever=retriever)
    gatherer.gather(_target(), repo)
    gatherer.gather(_target(), repo)
    assert len(calls) == 1  # indexed once, reused on the second target
