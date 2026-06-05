"""Strongly-typed run configuration.

:class:`RunConfig` is the single source of truth for how a run behaves. It is
an immutable dataclass tree so that configuration cannot drift mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LogLevel(str, Enum):
    """Supported logging verbosity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(str, Enum):
    """Supported log output formats."""

    TEXT = "text"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Logging subsystem configuration."""

    level: LogLevel = LogLevel.INFO
    format: LogFormat = LogFormat.TEXT
    file: Path | None = None


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Configuration for the optional LLM-assisted mutation provider."""

    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 2048
    temperature: float = 0.0
    timeout_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class CoverageConfig:
    """Coverage-collection configuration."""

    enabled: bool = True
    use_per_test_coverage: bool = False


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Sandbox-isolation configuration."""

    strategy: str = "copy"
    max_parallel: int = 4
    test_timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Artifact-storage and run-repository configuration."""

    backend: str = "filesystem"
    root: Path = field(default_factory=lambda: Path(".mutagen"))


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Top-level, immutable configuration for a mutation-testing run.

    Attributes:
        project_root: Root directory of the project under test.
        source_paths: Source files/directories eligible for mutation.
        test_paths: Locations of the test suite.
        operators: Names of mutation operators to enable; empty means all.
        score_threshold: Minimum acceptable mutation score in ``[0, 1]``.
        logging: Logging configuration.
        llm: LLM provider configuration.
        coverage: Coverage configuration.
        sandbox: Sandbox configuration.
        storage: Storage configuration.
    """

    project_root: Path
    source_paths: tuple[Path, ...] = field(default_factory=tuple)
    test_paths: tuple[Path, ...] = field(default_factory=tuple)
    operators: tuple[str, ...] = field(default_factory=tuple)
    score_threshold: float = 0.0
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    coverage: CoverageConfig = field(default_factory=CoverageConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
