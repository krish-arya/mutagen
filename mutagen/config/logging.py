"""Logging infrastructure setup.

Centralizes configuration of the standard-library logging system so that all
modules obtain consistently formatted, correctly-leveled loggers. Supports a
plain-text format for humans and a JSON Lines format for structured ingestion.

Structured fields are passed through the standard ``extra=`` mechanism; any
keys placed under the reserved ``"context"`` extra are merged into the emitted
record so call sites can attach correlation data (e.g. ``source``, ``attempt``)
without subclassing the logger.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mutagen.config.run_config import LogFormat, LoggingConfig

_LOGGER_NAMESPACE = "mutagen"

# Attributes present on a vanilla LogRecord; anything else a caller attached via
# ``extra=`` is treated as a structured field by the JSON formatter.
_RESERVED_RECORD_KEYS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class StructuredFormatter(logging.Formatter):
    """Render log records as single-line JSON objects.

    Standard fields (timestamp, level, logger, message) are always emitted.
    Any extra attributes attached to the record — including the contents of a
    ``context`` dict — are merged in as top-level keys, and exceptions are
    rendered into a ``"exception"`` field.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        context = record.__dict__.get("context")
        if isinstance(context, dict):
            payload.update(context)

        for key, value in record.__dict__.items():
            if key == "context" or key in _RESERVED_RECORD_KEYS:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def _build_formatter(log_format: LogFormat) -> logging.Formatter:
    """Construct the formatter for the requested format."""
    if log_format is LogFormat.JSON:
        return StructuredFormatter()
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def configure_logging(config: LoggingConfig) -> None:
    """Configure the root Mutagen logger from ``config``.

    Installs a stream handler (and an optional file handler) with the requested
    level and format on the ``mutagen`` namespace logger. It is idempotent:
    repeated calls replace previously installed Mutagen handlers rather than
    accumulating them, and it never touches the global root logger.

    Args:
        config: The logging configuration to apply.
    """
    logger = logging.getLogger(_LOGGER_NAMESPACE)
    logger.setLevel(config.level.value)
    # Don't propagate to the root logger; we own this namespace's handlers.
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = _build_formatter(config.format)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if config.file is not None:
        config.file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(config.file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for ``name``.

    Args:
        name: Dotted module name, typically ``__name__``.

    Returns:
        A :class:`logging.Logger` under the ``mutagen`` namespace.
    """
    if name == _LOGGER_NAMESPACE or name.startswith(f"{_LOGGER_NAMESPACE}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAMESPACE}.{name}")
