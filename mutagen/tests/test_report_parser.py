"""Unit tests for the pytest-json-report parser.

These feed the parser report-shaped JSON directly (no pytest run), covering
verdict mapping, per-id aggregation, collection errors, and malformed input.
"""

from __future__ import annotations

import json
from typing import Any

from mutagen.infrastructure.sandbox import ReportParser
from mutagen.infrastructure.sandbox import TestVerdict as Verdict


def _doc(tests: list[dict[str, Any]], **extra: Any) -> str:
    return json.dumps({"tests": tests, **extra})


def _ids() -> dict[str, str]:
    return {"test_mutagen_aaa.py": "aaa", "test_mutagen_bbb.py": "bbb"}


def test_parses_passed() -> None:
    raw = _doc([{"nodeid": "test_mutagen_aaa.py::test_x", "outcome": "passed"}])
    report = ReportParser().parse(raw, _ids())
    assert report.verdict_by_test_id == {"aaa": Verdict.PASSED}
    assert report.passed_ids() == frozenset({"aaa"})
    assert not report.collection_error


def test_parses_failed() -> None:
    raw = _doc([{"nodeid": "test_mutagen_aaa.py::test_x", "outcome": "failed"}])
    report = ReportParser().parse(raw, _ids())
    assert report.verdict_by_test_id == {"aaa": Verdict.FAILED}
    assert report.failed_ids() == frozenset({"aaa"})


def test_skipped_counts_as_success() -> None:
    raw = _doc(
        [{"nodeid": "test_mutagen_aaa.py::test_x", "outcome": "skipped"}]
    )
    report = ReportParser().parse(raw, _ids())
    assert report.passed_ids() == frozenset({"aaa"})


def test_error_in_phase_maps_to_error() -> None:
    raw = _doc(
        [
            {
                "nodeid": "test_mutagen_aaa.py::test_x",
                "outcome": "failed",
                "setup": {"outcome": "error"},
            }
        ]
    )
    report = ReportParser().parse(raw, _ids())
    assert report.verdict_by_test_id["aaa"] is Verdict.ERROR


def test_aggregates_worst_verdict_per_id() -> None:
    raw = _doc(
        [
            {"nodeid": "test_mutagen_aaa.py::test_a", "outcome": "passed"},
            {"nodeid": "test_mutagen_aaa.py::test_b", "outcome": "failed"},
        ]
    )
    report = ReportParser().parse(raw, _ids())
    # The failing function dominates the file's id verdict.
    assert report.verdict_by_test_id["aaa"] is Verdict.FAILED


def test_unmapped_nodeid_is_ignored() -> None:
    raw = _doc([{"nodeid": "test_other.py::test_x", "outcome": "passed"}])
    report = ReportParser().parse(raw, _ids())
    assert report.verdict_by_test_id == {}


def test_collection_error_detected() -> None:
    raw = _doc([], collectors=[{"outcome": "failed", "nodeid": "x"}])
    report = ReportParser().parse(raw, _ids())
    assert report.collection_error


def test_summary_error_detected() -> None:
    raw = _doc([], summary={"error": 1})
    report = ReportParser().parse(raw, _ids())
    assert report.collection_error


def test_invalid_json_flags_collection_error() -> None:
    report = ReportParser().parse("{not json", _ids())
    assert report.collection_error
    assert report.verdict_by_test_id == {}


def test_non_dict_document_flags_error() -> None:
    report = ReportParser().parse("[1, 2, 3]", _ids())
    assert report.collection_error


def test_windows_style_nodeid_path() -> None:
    # nodeids may use backslashes on Windows; the basename must still match.
    raw = _doc(
        [{"nodeid": "sub\\test_mutagen_aaa.py::test_x", "outcome": "passed"}]
    )
    report = ReportParser().parse(raw, _ids())
    assert report.passed_ids() == frozenset({"aaa"})
