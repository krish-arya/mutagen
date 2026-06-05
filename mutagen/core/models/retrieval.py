"""Retrieval domain models for retrieval-augmented generation (RAG).

Before prompting, the pipeline can **retrieve** the most relevant existing
material — similar functions and their tests — and fold it into the prompt, so
generated tests stay consistent with the project's real conventions instead of
being matched against an arbitrary first-couple-of-files heuristic:

.. code-block:: text

    target function ─► vector search ─► relevant existing tests ─► prompt

These are pure value objects in the domain layer so the
:class:`mutagen.core.interfaces.TestRetriever` and
:class:`mutagen.core.interfaces.EmbeddingProvider` ports can reference them
without depending on any infrastructure (embedding backends, vector stores).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetrievableDocument:
    """A chunk of source eligible for retrieval (typically a test snippet).

    Attributes:
        doc_id: Stable identifier for the chunk, unique within an index.
        text: The chunk's source text, included verbatim in prompts.
        path: Repo-relative path the chunk was drawn from.
        kind: Coarse category, e.g. ``"test"`` or ``"function"``, so retrieval
            can be scoped.
    """

    doc_id: str
    text: str
    path: Path
    kind: str = "test"


@dataclass(frozen=True, slots=True)
class RetrievedExample:
    """A retrieved document paired with its similarity to the query.

    Attributes:
        document: The matched :class:`RetrievableDocument`.
        score: Similarity in ``[0, 1]`` (1 = most similar). Higher is better.
    """

    document: RetrievableDocument
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """The text whose neighbours should be retrieved.

    Attributes:
        text: The query text — typically a target's source plus signature.
        top_k: Maximum number of examples to return.
        kinds: If non-empty, restrict results to documents of these kinds.
    """

    text: str
    top_k: int = 2
    kinds: tuple[str, ...] = field(default_factory=tuple)
