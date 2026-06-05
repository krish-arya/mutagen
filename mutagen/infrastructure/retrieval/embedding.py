"""A dependency-free embedding backend.

:class:`HashingEmbeddingProvider` implements the
:class:`mutagen.core.interfaces.EmbeddingProvider` port using the *hashing
trick*: it tokenizes text, hashes each token (and adjacent bigram) into a
fixed-width vector via a stable digest, accumulates signed counts, and
L2-normalizes the result. This is the classic ``HashingVectorizer`` idea minus
the heavyweight dependency.

It is deterministic, fast, needs no model download or API key, and produces
unit vectors whose dot product is cosine similarity — good enough to rank
"which existing test looks most like this target" for prompt seeding. For
higher semantic fidelity, swap in a real embedding model behind the same port;
nothing else in the pipeline changes.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from mutagen.core.interfaces import EmbeddingProvider

# Identifier-ish tokens: words and dotted/under_scored names. Lowercased so
# casing differences don't fragment the vocabulary.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")

_DEFAULT_DIM = 256


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic embeddings via the hashing trick over token n-grams.

    Args:
        dim: Vector dimensionality. Larger reduces hash collisions at a small
            memory/compute cost. Must be positive.
    """

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}.")
        self._dim = dim

    @property
    def dim(self) -> int:
        """The dimensionality of vectors this provider emits."""
        return self._dim

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed ``text`` into an L2-normalized vector of length :attr:`dim`."""
        vector = [0.0] * self._dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return tuple(vector)
        # Unigrams plus adjacent bigrams capture a little local structure
        # (e.g. ``def test`` vs ``test def``) without a real n-gram model.
        features = list(tokens)
        features += [f"{a}\x00{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for feature in features:
            index, sign = self._hash(feature)
            vector[index] += sign
        return self._normalize(vector)

    def _hash(self, feature: str) -> tuple[int, float]:
        """Map a feature to a (bucket, sign) pair via a stable digest."""
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % self._dim
        # The high bit picks the sign so collisions can cancel rather than
        # always reinforce — the standard signed hashing-trick refinement.
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    @staticmethod
    def _normalize(vector: list[float]) -> tuple[float, ...]:
        """Return the L2-normalized vector (unchanged if it is all zeros)."""
        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(component / norm for component in vector)

    def embed_batch(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed several strings (no batched fast path; calls :meth:`embed`)."""
        return tuple(self.embed(text) for text in texts)
