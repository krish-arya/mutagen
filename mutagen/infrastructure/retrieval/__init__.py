"""Retrieval adapters implementing the RAG ports.

Two collaborators back retrieval-augmented test generation:

* :class:`HashingEmbeddingProvider` — a dependency-free, deterministic
  :class:`mutagen.core.interfaces.EmbeddingProvider` over hashed token n-grams,
  so retrieval works out of the box with no model download or API key;
* :class:`EmbeddingTestRetriever` — an in-memory
  :class:`mutagen.core.interfaces.TestRetriever` that indexes existing test
  snippets and returns the most cosine-similar ones for a target.

A higher-fidelity embedding backend (local sentence-transformer, hosted API)
can implement :class:`EmbeddingProvider` and drop straight in.
"""

from mutagen.infrastructure.retrieval.corpus_indexer import CorpusIndexer
from mutagen.infrastructure.retrieval.embedding import HashingEmbeddingProvider
from mutagen.infrastructure.retrieval.retriever import EmbeddingTestRetriever

__all__ = [
    "HashingEmbeddingProvider",
    "EmbeddingTestRetriever",
    "CorpusIndexer",
]
