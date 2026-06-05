"""Tests for retrieval-augmented generation building blocks.

Cover the hashing embedding provider (determinism, normalization, similarity
ordering), the in-memory retriever (ranking, top-k, kind filtering, empty
index), and the test-corpus indexer (per-function chunking + fallbacks).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from mutagen.core.models.repo import RepoContext
from mutagen.core.models.retrieval import RetrievableDocument, RetrievalQuery
from mutagen.infrastructure.retrieval import (
    CorpusIndexer,
    EmbeddingTestRetriever,
    HashingEmbeddingProvider,
)

# --------------------------------------------------------------------------- #
# Embedding provider
# --------------------------------------------------------------------------- #


def test_embedding_is_deterministic() -> None:
    emb = HashingEmbeddingProvider(dim=64)
    assert emb.embed("calculate tax") == emb.embed("calculate tax")


def test_embedding_is_unit_normalized() -> None:
    emb = HashingEmbeddingProvider(dim=64)
    vec = emb.embed("def test_thing(): assert True")
    norm = math.sqrt(sum(c * c for c in vec))
    assert vec and math.isclose(norm, 1.0, rel_tol=1e-9)


def test_embedding_empty_text_is_zero_vector() -> None:
    emb = HashingEmbeddingProvider(dim=16)
    assert emb.embed("   ") == tuple([0.0] * 16)


def test_similar_text_scores_higher_than_unrelated() -> None:
    emb = HashingEmbeddingProvider(dim=512)
    base = emb.embed("calculate tax for an order amount")
    near = emb.embed("calculate tax on the order total")
    far = emb.embed("authenticate the user login session")

    def dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=False))

    assert dot(base, near) > dot(base, far)


def test_invalid_dim_rejected() -> None:
    with pytest.raises(ValueError):
        HashingEmbeddingProvider(dim=0)


# --------------------------------------------------------------------------- #
# Retriever
# --------------------------------------------------------------------------- #


@pytest.fixture
def retriever() -> EmbeddingTestRetriever:
    return EmbeddingTestRetriever(HashingEmbeddingProvider(dim=512))


def _doc(doc_id: str, text: str, kind: str = "test") -> RetrievableDocument:
    return RetrievableDocument(doc_id=doc_id, text=text, path=Path("t.py"), kind=kind)


def test_retrieve_ranks_by_similarity(retriever: EmbeddingTestRetriever) -> None:
    retriever.index(
        [
            _doc("tax", "def test_calculate_tax(): assert calculate_tax(100) == 10"),
            _doc("login", "def test_login(): assert login(user) is True"),
        ]
    )
    results = retriever.retrieve(
        RetrievalQuery(text="calculate_tax order amount tax", top_k=1)
    )
    assert len(results) == 1
    assert results[0].document.doc_id == "tax"


def test_retrieve_respects_top_k(retriever: EmbeddingTestRetriever) -> None:
    retriever.index(
        [_doc(str(i), f"def test_thing_{i}(): assert thing()") for i in range(5)]
    )
    results = retriever.retrieve(RetrievalQuery(text="test thing assert", top_k=2))
    assert len(results) <= 2


def test_retrieve_filters_by_kind(retriever: EmbeddingTestRetriever) -> None:
    retriever.index(
        [
            _doc("t", "def test_tax(): assert tax_amount == 10", kind="test"),
            _doc("f", "def calculate_tax(): return tax_amount", kind="function"),
        ]
    )
    results = retriever.retrieve(
        RetrievalQuery(text="tax tax_amount calculate", top_k=5, kinds=("test",))
    )
    assert {r.document.kind for r in results} == {"test"}


def test_retrieve_empty_index_returns_empty(
    retriever: EmbeddingTestRetriever,
) -> None:
    assert retriever.retrieve(RetrievalQuery(text="anything", top_k=3)) == ()


def test_reindexing_replaces_corpus(retriever: EmbeddingTestRetriever) -> None:
    retriever.index([_doc("old", "def test_old(): assert old_value == 1")])
    retriever.index([_doc("new", "def test_new(): assert new_value == 2")])
    results = retriever.retrieve(RetrievalQuery(text="test new_value assert", top_k=5))
    assert {r.document.doc_id for r in results} == {"new"}


# --------------------------------------------------------------------------- #
# Corpus indexer
# --------------------------------------------------------------------------- #


def test_indexer_chunks_per_test_function(tmp_path: Path) -> None:
    (tmp_path / "test_mod.py").write_text(
        "import pytest\n"
        "def test_a():\n    assert True\n"
        "def test_b():\n    assert 1 == 1\n"
        "def helper():\n    return 1\n",
        encoding="utf-8",
    )
    ctx = RepoContext(root=tmp_path.resolve(), test_files=(Path("test_mod.py"),))
    docs = CorpusIndexer().build(ctx)
    ids = {d.doc_id for d in docs}
    assert ids == {"test_mod.py::test_a", "test_mod.py::test_b"}


def test_indexer_falls_back_to_whole_module(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef client():\n    return object()\n",
        encoding="utf-8",
    )
    ctx = RepoContext(root=tmp_path.resolve(), test_files=(Path("conftest.py"),))
    docs = CorpusIndexer().build(ctx)
    assert len(docs) == 1
    assert docs[0].doc_id == "conftest.py"


def test_indexer_skips_unparsable_file(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def test_x(:\n", encoding="utf-8")
    ctx = RepoContext(root=tmp_path.resolve(), test_files=(Path("broken.py"),))
    assert CorpusIndexer().build(ctx) == []
