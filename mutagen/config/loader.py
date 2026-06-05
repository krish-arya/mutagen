"""Configuration loading.

Resolves a :class:`RunConfig` from a configuration file and/or environment
overrides. Business logic (parsing, validation, merging) is intentionally
deferred; this module only declares the contract and entry point.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.config.run_config import RunConfig


def load_config(
    *,
    config_path: Path | None = None,
    overrides: dict[str, object] | None = None,
) -> RunConfig:
    """Load and validate a :class:`RunConfig`.

    Args:
        config_path: Optional path to a configuration file (e.g. TOML).
        overrides: Optional flat mapping of CLI/env overrides to merge on top
            of file values.

    Returns:
        A fully-resolved, immutable :class:`RunConfig`.

    Raises:
        ConfigurationError: If the configuration is missing or invalid.
    """
    raise NotImplementedError("Configuration loading is not yet implemented.")
