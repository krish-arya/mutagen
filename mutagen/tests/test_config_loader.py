"""Tests for the TOML config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.config import load_config
from mutagen.config.run_config import Effort, LogLevel
from mutagen.core.exceptions import ConfigurationError


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_when_no_file() -> None:
    config = load_config()
    assert config.project_root == Path(".")
    assert config.score_threshold == 0.0
    assert config.llm.model == "claude-opus-4-8"


def test_loads_full_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "m.toml",
        'project_root = "/proj"\n'
        "score_threshold = 0.85\n"
        "[logging]\n"
        'level = "debug"\n'
        'format = "json"\n'
        "[llm]\n"
        'model = "claude-opus-4-8"\n'
        'effort = "max"\n'
        "max_tokens = 8000\n"
        "[orchestrator]\n"
        "max_targets = 25\n"
        "max_cost_usd = 5.0\n"
        "[storage]\n"
        'backend = "sqlite"\n'
        'root = ".data"\n',
    )
    config = load_config(config_path=path)
    assert config.score_threshold == 0.85
    assert config.logging.level is LogLevel.DEBUG
    assert config.llm.effort is Effort.MAX
    assert config.llm.max_tokens == 8000
    assert config.orchestrator.max_targets == 25
    assert config.orchestrator.max_cost_usd == 5.0
    assert config.storage.root == Path(".data")


def test_partial_file_uses_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.toml", "score_threshold = 0.5\n")
    config = load_config(config_path=path)
    assert config.score_threshold == 0.5
    assert config.llm.model == "claude-opus-4-8"  # default
    assert config.orchestrator.max_repair_attempts == 2  # default


def test_overrides_take_precedence(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.toml", "score_threshold = 0.5\n")
    config = load_config(
        config_path=path,
        overrides={"score_threshold": 0.95, "log_level": "ERROR"},
    )
    assert config.score_threshold == 0.95
    assert config.logging.level is LogLevel.ERROR


def test_missing_file_raises() -> None:
    with pytest.raises(ConfigurationError):
        load_config(config_path=Path("does-not-exist.toml"))


def test_malformed_toml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "bad.toml", "this is = = not toml\n")
    with pytest.raises(ConfigurationError):
        load_config(config_path=path)


def test_invalid_enum_value_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.toml", '[logging]\nlevel = "verbose"\n')
    with pytest.raises(ConfigurationError):
        load_config(config_path=path)
