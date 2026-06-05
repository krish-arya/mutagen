"""Tests for the logging infrastructure.

Verifies the structured (JSON) formatter emits parseable records with merged
context, and that ``configure_logging`` is idempotent.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mutagen.config.logging import (
    StructuredFormatter,
    configure_logging,
    get_logger,
)
from mutagen.config.run_config import LogFormat, LoggingConfig, LogLevel


def _record(**extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord(
        {
            "name": "mutagen.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "hello %s",
            "args": ("world",),
        }
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_structured_formatter_emits_json() -> None:
    formatter = StructuredFormatter()
    payload = json.loads(formatter.format(_record()))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "mutagen.test"
    assert "timestamp" in payload


def test_structured_formatter_merges_context() -> None:
    formatter = StructuredFormatter()
    payload = json.loads(
        formatter.format(_record(context={"source": "repo", "attempt": 2}))
    )
    assert payload["source"] == "repo"
    assert payload["attempt"] == 2


def test_structured_formatter_renders_exception() -> None:
    formatter = StructuredFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record()
        record.exc_info = sys.exc_info()
    payload = json.loads(formatter.format(record))
    assert "ValueError: boom" in payload["exception"]


def test_configure_logging_is_idempotent() -> None:
    config = LoggingConfig(level=LogLevel.DEBUG, format=LogFormat.JSON)
    configure_logging(config)
    configure_logging(config)
    logger = logging.getLogger("mutagen")
    # Exactly one stream handler, not accumulated across calls.
    assert len(logger.handlers) == 1
    assert logger.level == logging.DEBUG


def test_configure_logging_writes_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "mutagen.log"
    configure_logging(LoggingConfig(format=LogFormat.JSON, file=log_file))
    get_logger("mutagen.filetest").info("written", extra={"context": {"k": 1}})
    logging.getLogger("mutagen").handlers[-1].flush()
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert json.loads(line)["k"] == 1
