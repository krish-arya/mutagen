"""Parsing of ``pytest-json-report`` output into per-test outcomes.

The sandbox runs pytest with ``--json-report``; this module turns the resulting
JSON document into a normalized :class:`RunReport` of per-test verdicts, keyed
by the generated-test id encoded in each test file's name.

Parsing is pure (a function over the JSON text) so it is exercised directly by
tests without running pytest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mutagen.config.logging import get_logger

_logger = get_logger(__name__)


class TestVerdict(str, Enum):
    """Per-test outcome as reported by pytest."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"

    @property
    def is_success(self) -> bool:
        """Whether this verdict counts as the test passing.

        Skipped tests are treated as successes: they did not fail, so they
        neither block nor (on their own) kill a mutant.
        """
        return self in (TestVerdict.PASSED, TestVerdict.SKIPPED)


@dataclass(frozen=True, slots=True)
class RunReport:
    """Normalized per-test results from one pytest invocation.

    Attributes:
        verdict_by_test_id: Map of generated-test id to its aggregated verdict.
        collection_error: Whether pytest failed to collect/import the tests
            (e.g. an ImportError in a test module), as opposed to a test
            assertion failing.
    """

    verdict_by_test_id: dict[str, TestVerdict] = field(default_factory=dict)
    collection_error: bool = False

    def passed_ids(self) -> frozenset[str]:
        """Ids whose aggregated verdict is a success."""
        return frozenset(
            tid
            for tid, v in self.verdict_by_test_id.items()
            if v.is_success
        )

    def failed_ids(self) -> frozenset[str]:
        """Ids whose aggregated verdict is a failure or error."""
        return frozenset(
            tid
            for tid, v in self.verdict_by_test_id.items()
            if not v.is_success
        )


class ReportParser:
    """Parses ``pytest-json-report`` documents into :class:`RunReport`."""

    def parse(
        self, raw: str, id_by_filename: dict[str, str]
    ) -> RunReport:
        """Parse a JSON report, mapping nodeids back to generated-test ids.

        Args:
            raw: The JSON report text written by ``pytest-json-report``.
            id_by_filename: Map of test *filename* (basename, no directory) to
                the generated-test id it was written for. Each test's nodeid
                begins with its filename, which is how outcomes are attributed.

        Returns:
            A :class:`RunReport`. When the JSON cannot be parsed, an empty
            report flagged as a ``collection_error`` is returned rather than
            raising, so a malformed run degrades to "errored" downstream.
        """
        try:
            document: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            _logger.warning(
                "could not parse pytest json report",
                extra={"context": {"error": str(exc)}},
            )
            return RunReport(collection_error=True)

        if not isinstance(document, dict):
            return RunReport(collection_error=True)

        collection_error = self._has_collection_error(document)

        # Aggregate per-test-id: a file may hold several test functions; the
        # worst outcome among them is the id's verdict.
        worst: dict[str, TestVerdict] = {}
        for test in document.get("tests", []):
            if not isinstance(test, dict):
                continue
            nodeid = str(test.get("nodeid", ""))
            test_id = self._match_id(nodeid, id_by_filename)
            if test_id is None:
                continue
            verdict = self._verdict(test)
            worst[test_id] = self._worse(worst.get(test_id), verdict)

        return RunReport(
            verdict_by_test_id=worst,
            collection_error=collection_error,
        )

    @staticmethod
    def _match_id(
        nodeid: str, id_by_filename: dict[str, str]
    ) -> str | None:
        """Resolve a pytest nodeid to a generated-test id by its filename."""
        # nodeid looks like "test_generated_abcd.py::test_fn"; the part before
        # "::" is a path whose basename is the file we wrote.
        path_part = nodeid.split("::", 1)[0]
        filename = path_part.replace("\\", "/").rsplit("/", 1)[-1]
        return id_by_filename.get(filename)

    @staticmethod
    def _verdict(test: dict[str, Any]) -> TestVerdict:
        """Derive a test's verdict, accounting for setup/call/teardown errors.

        A test that errored during setup/teardown reports ``outcome`` values
        that map to :attr:`TestVerdict.ERROR`; a failed assertion maps to
        ``FAILED``.
        """
        outcome = str(test.get("outcome", "")).lower()
        # An error in any phase is an error, not a plain failure.
        for phase in ("setup", "call", "teardown"):
            stage = test.get(phase)
            if isinstance(stage, dict) and stage.get("outcome") == "error":
                return TestVerdict.ERROR
        if outcome == "passed":
            return TestVerdict.PASSED
        if outcome == "skipped":
            return TestVerdict.SKIPPED
        if outcome == "error":
            return TestVerdict.ERROR
        return TestVerdict.FAILED

    @staticmethod
    def _worse(
        current: TestVerdict | None, candidate: TestVerdict
    ) -> TestVerdict:
        """Return the more severe of two verdicts (ERROR > FAILED > others)."""
        if current is None:
            return candidate
        severity = {
            TestVerdict.PASSED: 0,
            TestVerdict.SKIPPED: 0,
            TestVerdict.FAILED: 1,
            TestVerdict.ERROR: 2,
        }
        return candidate if severity[candidate] > severity[current] else current

    @staticmethod
    def _has_collection_error(document: dict[str, Any]) -> bool:
        """Whether the report indicates a collection/import failure."""
        # pytest-json-report records collectors; a failed collector means the
        # test module could not be imported.
        for collector in document.get("collectors", []):
            if (
                isinstance(collector, dict)
                and collector.get("outcome") == "failed"
            ):
                return True
        summary = document.get("summary", {})
        if isinstance(summary, dict) and summary.get("error"):
            return True
        return False
