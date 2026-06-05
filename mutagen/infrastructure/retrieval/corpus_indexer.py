"""Building a retrievable corpus from a repository's existing tests.

:class:`CorpusIndexer` reads the project's test modules and splits each into
per-test-function chunks (falling back to whole-module chunks when a file has no
discrete ``test_*`` functions). Each chunk becomes a
:class:`RetrievableDocument` that the retriever can match against a target.

Indexing at function granularity — rather than whole files — means a query for
``calculate_tax`` can surface the single most relevant existing test, not just
"some file that happens to contain it," which keeps the retrieved style example
tight and on-topic.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.core.models.repo import RepoContext
from mutagen.core.models.retrieval import RetrievableDocument

_logger = get_logger(__name__)

# Keep individual chunks prompt-sized; longer test bodies are truncated.
_MAX_CHUNK_CHARS = 2000


@dataclass(slots=True)
class CorpusIndexer:
    """Extracts retrievable test-function chunks from a repository snapshot."""

    max_chunk_chars: int = _MAX_CHUNK_CHARS

    def build(self, context: RepoContext) -> list[RetrievableDocument]:
        """Return one document per discovered test function (or module).

        Unparsable files are skipped with a warning rather than aborting.
        """
        documents: list[RetrievableDocument] = []
        for rel in context.test_files:
            source = self._read(context.root / rel)
            if not source.strip():
                continue
            chunks = self._chunk_file(source, rel)
            documents.extend(chunks)
        return documents

    def _chunk_file(self, source: str, rel: Path) -> list[RetrievableDocument]:
        """Split one test module into per-test-function documents."""
        try:
            tree = ast.parse(source, filename=str(rel))
        except SyntaxError as exc:
            _logger.warning(
                "skipping unparsable test file in retrieval index",
                extra={"context": {"path": str(rel), "error": str(exc)}},
            )
            return []

        documents: list[RetrievableDocument] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test"):
                    continue
                segment = ast.get_source_segment(source, node)
                if not segment:
                    continue
                documents.append(
                    RetrievableDocument(
                        doc_id=f"{rel}::{node.name}",
                        text=self._trim(segment),
                        path=rel,
                        kind="test",
                    )
                )
        # No discrete test functions: fall back to the whole module as one doc.
        if not documents:
            documents.append(
                RetrievableDocument(
                    doc_id=str(rel),
                    text=self._trim(source),
                    path=rel,
                    kind="test",
                )
            )
        return documents

    def _trim(self, text: str) -> str:
        if len(text) <= self.max_chunk_chars:
            return text
        return text[: self.max_chunk_chars] + "\n# ... (truncated)"

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
