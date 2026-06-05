"""Shared pytest fixtures.

Provides reusable configuration and domain fixtures for the test suite. Test
bodies are added alongside the corresponding implementation work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.config.run_config import RunConfig


@pytest.fixture
def run_config(tmp_path: Path) -> RunConfig:
    """A minimal, valid :class:`RunConfig` rooted in a temp directory."""
    return RunConfig(
        project_root=tmp_path,
        source_paths=(tmp_path / "src",),
        test_paths=(tmp_path / "tests",),
    )
