"""An in-memory vector retriever.

:class:`EmbeddingTestRetriever` implements the
:class:`mutagen.core.interfaces.TestRetriever` port. It embeds each indexed
document once via an injected :class:`EmbeddingProvider`, stores the vectors,
and answers a query by embedding it and returning the top-``k`` documents by
cosine similarity.

The corpus for a single repository is small (a few hundred test snippets at
most), so a brute-force scan is both simplest and fast enough; there is no need
for an ANN index. Because the provider emits L2-normalized vectors, cosine
similarity is just a dot product.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mutagen.core.interfaces import EmbeddingProvider, TestRetriever
from mutagen.core.models.retrieval import (
    RetrievableDocument,
    RetrievalQuery,
    RetrievedExample,
)


@dataclass(slots=True)
class _IndexedDocument:
    """An indexed document paired with its precomputed embedding."""

    document: RetrievableDocument
    vector: tuple[float, ...]


class EmbeddingTestRetriever(TestRetriever):
    """Brute-force cosine-similarity retriever over embedded documents.

    Args:
        embedder: The :class:`EmbeddingProvider` used to vectorize documents
            and queries. The same instance must be used for both so vectors are
            comparable.
    """

    def __init__(self, embedder: EmbeddingProvider) -> None:
        self._embedder = embedder
        self._index: list[_IndexedDocument] = []

    def index(self, documents: Sequence[RetrievableDocument]) -> None:
        """Embed and store ``documents``, replacing any existing index."""
        texts = [doc.text for doc in documents]
        vectors = self._embedder.embed_batch(texts) if texts else ()
        self._index = [
            _IndexedDocument(document=doc, vector=vec)
            for doc, vec in zip(documents, vectors, strict=False)
        ]

    def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedExample]:
        """Return up to ``query.top_k`` documents most similar to the query."""
        if not self._index or query.top_k <= 0 or not query.text.strip():
            return ()
        query_vec = self._embedder.embed(query.text)
        kinds = set(query.kinds)
        scored: list[RetrievedExample] = []
        for entry in self._index:
            if kinds and entry.document.kind not in kinds:
                continue
            score = self._cosine(query_vec, entry.vector)
            if score > 0.0:
                scored.append(RetrievedExample(document=entry.document, score=score))
        scored.sort(key=lambda ex: ex.score, reverse=True)
        return tuple(scored[: query.top_k])

    @staticmethod
    def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        """Dot product of two equal-length vectors (cosine for unit vectors).

        Guards against dimension mismatch (e.g. an empty zero-vector) by
        scanning only the overlapping prefix.
        """
        if not a or not b:
            return 0.0
        return sum(x * y for x, y in zip(a, b, strict=False))
