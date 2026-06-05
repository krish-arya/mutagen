"""Logging infrastructure setup.

Centralizes configuration of the standard-library logging system so that all
modules obtain consistently formatted, correctly-leveled loggers.
"""

from __future__ import annotations

import logging

from mutagen.config.run_config import LoggingConfig

_LOGGER_NAMESPACE = "mutagen"


def configure_logging(config: LoggingConfig) -> None:
    """Configure the root Mutagen logger from ``config``.

    This installs handlers and formatters according to the requested level,
    format, and optional log file. It is idempotent across calls.

    Args:
        config: The logging configuration to apply.
    """
    raise NotImplementedError("Logging configuration is not yet implemented.")


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
