"""Retrieval ports for retrieval-augmented generation (RAG).

Two collaborating ports:

* :class:`EmbeddingProvider` turns text into a dense vector, so similarity can
  be measured numerically.
* :class:`TestRetriever` indexes a corpus of :class:`RetrievableDocument` and,
  given a :class:`RetrievalQuery`, returns the most similar documents.

Splitting them keeps the *retrieval strategy* (chunking, indexing, ranking)
independent of the *embedding backend* (hashing, local model, hosted API). How
vectors are produced and searched is an implementation concern; the ports speak
only in domain models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from mutagen.core.models.retrieval import (
    RetrievableDocument,
    RetrievalQuery,
    RetrievedExample,
)


class EmbeddingProvider(ABC):
    """Port for turning text into a dense embedding vector."""

    @abstractmethod
    def embed(self, text: str) -> tuple[float, ...]:
        """Embed a single string into a fixed-length vector.

        Args:
            text: The text to embed.

        Returns:
            A fixed-length vector. Implementations must return vectors of the
            same dimensionality for every input so they are comparable.
        """
        raise NotImplementedError

    def embed_batch(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed several strings. Defaults to per-item :meth:`embed`.

        Backends with cheaper batched paths should override this.
        """
        return tuple(self.embed(text) for text in texts)


class TestRetriever(ABC):
    """Port for retrieving the most relevant documents for a query."""

    @abstractmethod
    def index(self, documents: Sequence[RetrievableDocument]) -> None:
        """Index ``documents`` so they can be retrieved.

        Calling :meth:`index` replaces any previously indexed corpus. Indexing
        an empty sequence clears the index.
        """
        raise NotImplementedError

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedExample]:
        """Return up to ``query.top_k`` documents most similar to the query.

        Args:
            query: The retrieval query.

        Returns:
            Matches in descending similarity order. Empty if the index is empty
            or nothing matches the requested kinds.
        """
        raise NotImplementedError
