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


class Effort(str, Enum):
    """Effort levels controlling thinking depth and token spend.

    Maps to the Anthropic ``output_config.effort`` parameter. ``MAX`` is
    Opus-tier only. Higher effort trades latency and cost for capability.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Configuration for the optional LLM-assisted generation provider.

    Targets the Anthropic Messages API with adaptive thinking. Note there is
    no ``temperature`` field: Opus 4.7+ rejects sampling parameters, so the
    model is steered via prompting and :attr:`effort` instead.

    Attributes:
        enabled: Whether LLM-assisted generation is active.
        provider: Provider name; only ``"anthropic"`` is supported today.
        model: Model identifier (e.g. ``"claude-opus-4-8"``).
        api_key_env: Environment variable holding the API key.
        max_tokens: Hard cap on output tokens per request.
        effort: Thinking/effort level for requests.
        adaptive_thinking: Whether to enable adaptive thinking.
        timeout_seconds: Per-request timeout passed to the SDK.
        max_retries: Additional retry attempts for transient API failures
            (rate limits, 5xx), on top of the SDK's own retry handling.
        retry_backoff_seconds: Base delay for the adapter's backoff between
            its own retries.
        input_usd_per_mtok: Input price in USD per million tokens, for cost
            estimation.
        output_usd_per_mtok: Output price in USD per million tokens.
    """

    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 4096
    effort: Effort = Effort.HIGH
    adaptive_thinking: bool = True
    timeout_seconds: float = 120.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    input_usd_per_mtok: float = 5.0
    output_usd_per_mtok: float = 25.0


@dataclass(frozen=True, slots=True)
class CoverageConfig:
    """Coverage-collection configuration."""

    enabled: bool = True
    use_per_test_coverage: bool = False


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Sandbox-isolation configuration.

    Attributes:
        strategy: How isolation is provisioned (e.g. ``"copy"``).
        max_parallel: Maximum concurrent sandbox evaluations.
        test_timeout_seconds: Wall-clock timeout for a single test execution.
        cpu_time_limit_seconds: Per-process CPU-time rlimit (``RLIMIT_CPU``).
            Enforced on POSIX via ``setrlimit``; a no-op on platforms without
            it (e.g. Windows), where the wall-clock timeout still applies.
            ``0`` disables the CPU limit.
        memory_limit_mb: Per-process address-space rlimit (``RLIMIT_AS``) in
            mebibytes, enforced the same way. ``0`` disables the memory limit.
        detect_flakiness: Whether to run the suite twice and flag tests whose
            verdict differs between runs.
        max_output_chars: Cap on captured stdout/stderr length retained in the
            result.
    """

    strategy: str = "copy"
    max_parallel: int = 4
    test_timeout_seconds: float = 30.0
    cpu_time_limit_seconds: int = 60
    memory_limit_mb: int = 1024
    detect_flakiness: bool = True
    max_output_chars: int = 20_000


@dataclass(frozen=True, slots=True)
class MutationConfig:
    """Mutation-gate (mutmut) configuration.

    Controls how the :class:`mutagen.core.interfaces.MutationGate` runs mutmut
    against a target's generated tests and decides whether to keep them.

    Attributes:
        score_threshold: Minimum mutation score (killed / scored) required to
            keep the tests, in ``[0, 1]``.
        max_mutants: Cap on the number of mutants evaluated per target; ``0``
            means no cap. Bounds runtime on large targets.
        timeout_seconds: Wall-clock timeout for the whole mutmut run.
        per_mutant_timeout_seconds: Timeout mutmut applies per individual test
            run, passed through to its baseline-time/timeout behavior.
        max_survivors_in_feedback: Maximum number of surviving mutants detailed
            in the generated feedback string.
        max_feedback_chars: Cap on the length of the survivor-feedback string.
    """

    score_threshold: float = 0.8
    max_mutants: int = 50
    timeout_seconds: float = 600.0
    per_mutant_timeout_seconds: float = 10.0
    max_survivors_in_feedback: int = 10
    max_feedback_chars: int = 4000


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Target-selection and ranking configuration.

    Controls how the :class:`mutagen.core.interfaces.TargetSelector` filters
    and ranks candidate functions. Defaults aim for "test the meaty,
    under-covered functions and skip the noise."

    Attributes:
        trivial_max_statements: Functions with at most this many body
            statements are considered trivial and filtered out.
        giant_max_statements: Functions with more than this many body
            statements are considered giant and filtered out (too large to
            generate meaningful tests for in one pass).
        exclude_property_getters: Whether to drop ``@property`` getters.
        coverage_weight: Weight of the under-coverage term in the priority
            score.
        size_weight: Weight of the (normalized) size term in the priority
            score.
        max_targets: Optional cap on the number of targets returned; ``0``
            means unlimited.
    """

    trivial_max_statements: int = 1
    giant_max_statements: int = 80
    exclude_property_getters: bool = True
    coverage_weight: float = 0.8
    size_weight: float = 0.2
    max_targets: int = 0


@dataclass(frozen=True, slots=True)
class IngestConfig:
    """Repository-ingestion configuration.

    Controls how the :class:`mutagen.core.interfaces.RepoIngestor` acquires a
    repository (clone/copy), provisions an isolated virtualenv, and installs
    dependencies. Every heavyweight, host-touching step is individually
    gated so runs and tests can opt out.

    Attributes:
        workspace_root: Directory under which isolated working copies are
            created. Each ingest gets a fresh subdirectory beneath it.
        create_venv: Whether to create a per-repo virtualenv.
        install_deps: Whether to install detected dependencies into the venv.
        clone_depth: Git shallow-clone depth; ``0`` means a full clone.
        command_timeout_seconds: Per-subprocess timeout (clone, venv, pip).
        max_retries: Number of additional attempts for retryable subprocess
            failures (network clone / pip install). ``0`` disables retries.
        retry_backoff_seconds: Base delay for exponential backoff between
            retries.
        pip_extra_args: Extra arguments appended to ``pip install`` invocations.
    """

    workspace_root: Path = field(
        default_factory=lambda: Path(".mutagen") / "workspaces"
    )
    create_venv: bool = True
    install_deps: bool = True
    clone_depth: int = 1
    command_timeout_seconds: float = 600.0
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    pip_extra_args: tuple[str, ...] = field(default_factory=tuple)


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
        ingest: Repository-ingestion configuration.
        selection: Target-selection configuration.
        mutation: Mutation-gate (mutmut) configuration.
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
    ingest: IngestConfig = field(default_factory=IngestConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    mutation: MutationConfig = field(default_factory=MutationConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
