"""Parsing of mutmut results into :class:`MutationResult` records.

mutmut's results surface has shifted across versions, so this parser is
deliberately tolerant: it prefers a machine-readable JSON export when one is
available and falls back to parsing the human-readable ``mutmut results`` text
otherwise. Both paths produce the same normalized list of
:class:`MutationResult`.

Parsing is pure (functions over text) so it is exercised directly by tests
without running mutmut.
"""

from __future__ import annotations

import json
import re
from typing import Any

from mutagen.config.logging import get_logger
from mutagen.core.models.outcome import MutationResult, MutationVerdict

_logger = get_logger(__name__)

# mutmut status tokens -> our verdicts. mutmut uses a handful of synonyms
# across versions (killed/ok, survived/bad/suspicious, timeout, error).
_STATUS_VERDICTS: dict[str, MutationVerdict] = {
    "killed": MutationVerdict.KILLED,
    "ok_killed": MutationVerdict.KILLED,
    "bad_killed": MutationVerdict.KILLED,
    "survived": MutationVerdict.SURVIVED,
    "bad_survived": MutationVerdict.SURVIVED,
    "ok_survived": MutationVerdict.SURVIVED,
    "suspicious": MutationVerdict.SURVIVED,
    "timeout": MutationVerdict.TIMEOUT,
    "ok_timeout": MutationVerdict.TIMEOUT,
    "error": MutationVerdict.ERROR,
    "skipped": MutationVerdict.ERROR,
}

# Matches a line of `mutmut results` text such as:
#   "Survived 🙁 (3)\n\n---- module.py (3) ----\n1-2, 5"
# We instead parse the simpler per-id form mutmut also emits with --json or
# the legacy "<id>: <status>" listing.
_TEXT_LINE_RE = re.compile(
    r"^\s*(?P<id>[\w./:-]+)\s*[:=]\s*(?P<status>[a-z_]+)\s*$",
    re.IGNORECASE,
)


class MutmutParser:
    """Parses mutmut output into normalized mutation results."""

    def parse(self, raw: str, killing_test_ids: tuple[str, ...] = ()) -> list[MutationResult]:
        """Parse mutmut output, trying JSON first then a text fallback.

        Args:
            raw: The captured mutmut results output (JSON or text).
            killing_test_ids: Test ids credited with kills. mutmut reports
                kills at the suite level rather than per-test, so every killed
                mutant is attributed to the whole supplied suite.

        Returns:
            A list of :class:`MutationResult`, one per reported mutant.
        """
        text = raw.strip()
        if not text:
            return []
        parsed = self._try_json(text, killing_test_ids)
        if parsed is not None:
            return parsed
        return self._parse_text(text, killing_test_ids)

    # ------------------------------------------------------------------ #
    # JSON path (preferred)
    # ------------------------------------------------------------------ #

    def _try_json(
        self, text: str, killing_test_ids: tuple[str, ...]
    ) -> list[MutationResult] | None:
        """Parse a JSON export, or return ``None`` if it is not JSON."""
        try:
            document: Any = json.loads(text)
        except json.JSONDecodeError:
            return None

        records = self._json_records(document)
        if records is None:
            return None

        results: list[MutationResult] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            mutant_id = str(
                record.get("id")
                or record.get("mutant_id")
                or record.get("name")
                or ""
            ).strip()
            status = str(record.get("status") or record.get("result") or "").lower()
            if not mutant_id or not status:
                continue
            results.append(
                self._build(mutant_id, status, killing_test_ids, record)
            )
        return results

    @staticmethod
    def _json_records(document: Any) -> list[Any] | None:
        """Locate the list of mutant records within a JSON document."""
        if isinstance(document, list):
            return document
        if isinstance(document, dict):
            for key in ("mutants", "results", "tests"):
                value = document.get(key)
                if isinstance(value, list):
                    return value
        return None

    # ------------------------------------------------------------------ #
    # Text fallback
    # ------------------------------------------------------------------ #

    def _parse_text(
        self, text: str, killing_test_ids: tuple[str, ...]
    ) -> list[MutationResult]:
        """Parse the per-id ``<id>: <status>`` listing form."""
        results: list[MutationResult] = []
        for line in text.splitlines():
            match = _TEXT_LINE_RE.match(line)
            if match is None:
                continue
            results.append(
                self._build(
                    match.group("id"),
                    match.group("status").lower(),
                    killing_test_ids,
                    {},
                )
            )
        if not results:
            _logger.warning(
                "mutmut output matched no known result format",
                extra={"context": {"head": text[:200]}},
            )
        return results

    # ------------------------------------------------------------------ #
    # Shared
    # ------------------------------------------------------------------ #

    def _build(
        self,
        mutant_id: str,
        status: str,
        killing_test_ids: tuple[str, ...],
        record: dict[str, Any],
    ) -> MutationResult:
        """Build a :class:`MutationResult` from a status token and record."""
        verdict = _STATUS_VERDICTS.get(status, MutationVerdict.ERROR)
        # A KILLED result must name a killing test to satisfy the model
        # invariant; fall back to a synthetic credit when the suite is unknown.
        killers: tuple[str, ...] = ()
        if verdict is MutationVerdict.KILLED:
            killers = killing_test_ids or ("<suite>",)
        detail = str(record.get("detail") or record.get("diff") or "")
        return MutationResult(
            mutant_id=mutant_id,
            verdict=verdict,
            killing_test_ids=killers,
            detail=detail,
        )
