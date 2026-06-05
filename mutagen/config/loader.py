"""Configuration loading.

Resolves a :class:`RunConfig` from an optional TOML file plus a flat mapping of
CLI/environment overrides. The TOML layout mirrors the config dataclass tree —
a top-level table for run-wide settings and one sub-table per component:

    project_root = "."
    score_threshold = 0.8

    [logging]
    level = "INFO"
    format = "json"

    [llm]
    model = "claude-opus-4-8"
    enabled = true

    [orchestrator]
    max_targets = 50
    max_cost_usd = 5.0

    [storage]
    backend = "sqlite"
    root = ".mutagen"

Unknown keys are ignored; missing tables fall back to dataclass defaults.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from mutagen.config.run_config import (
    Effort,
    GenerationConfig,
    LLMConfig,
    LogFormat,
    LoggingConfig,
    LogLevel,
    MutationConfig,
    OrchestratorConfig,
    RunConfig,
    SandboxConfig,
    StorageConfig,
)
from mutagen.core.exceptions import ConfigurationError


def load_config(
    *,
    config_path: Path | None = None,
    overrides: dict[str, object] | None = None,
) -> RunConfig:
    """Load and validate a :class:`RunConfig`.

    Args:
        config_path: Optional path to a TOML configuration file.
        overrides: Optional flat mapping merged on top of file values. Keys:
            ``project_root``, ``score_threshold``, ``log_level``, ``log_file``.

    Returns:
        A fully-resolved, immutable :class:`RunConfig`.

    Raises:
        ConfigurationError: If the file is missing/malformed, or the resolved
            configuration is invalid.
    """
    data = _read_file(config_path) if config_path else {}
    merged = _apply_overrides(data, overrides or {})

    try:
        return _build(merged)
    except (KeyError, ValueError, TypeError) as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc


def _read_file(path: Path) -> dict[str, Any]:
    """Parse a TOML config file into a dict."""
    if not path.is_file():
        raise ConfigurationError(f"Config file not found: {path}.")
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"Could not read config {path}: {exc}") from exc


def _apply_overrides(
    data: dict[str, Any], overrides: dict[str, object]
) -> dict[str, Any]:
    """Merge CLI/env overrides into the parsed config dict."""
    merged = dict(data)
    if "project_root" in overrides and overrides["project_root"] is not None:
        merged["project_root"] = overrides["project_root"]
    if "score_threshold" in overrides and overrides["score_threshold"] is not None:
        merged["score_threshold"] = overrides["score_threshold"]
    if "log_level" in overrides and overrides["log_level"] is not None:
        logging = dict(merged.get("logging", {}))
        logging["level"] = overrides["log_level"]
        merged["logging"] = logging
    if "log_file" in overrides and overrides["log_file"] is not None:
        logging = dict(merged.get("logging", {}))
        logging["file"] = overrides["log_file"]
        merged["logging"] = logging
    return merged


def _build(data: dict[str, Any]) -> RunConfig:
    """Construct a :class:`RunConfig` from a merged config dict."""
    project_root = Path(str(data.get("project_root", ".")))
    config = RunConfig(
        project_root=project_root,
        score_threshold=float(data.get("score_threshold", 0.0)),
        logging=_logging(data.get("logging", {})),
        llm=_llm(data.get("llm", {})),
        generation=_generation(data.get("generation", {})),
        sandbox=_sandbox(data.get("sandbox", {})),
        mutation=_mutation(data.get("mutation", {})),
        orchestrator=_orchestrator(data.get("orchestrator", {})),
        storage=_storage(data.get("storage", {})),
    )
    return config


def _logging(table: dict[str, Any]) -> LoggingConfig:
    file = table.get("file")
    return LoggingConfig(
        level=LogLevel(str(table.get("level", "INFO")).upper()),
        format=LogFormat(str(table.get("format", "text")).lower()),
        file=Path(str(file)) if file else None,
    )


def _llm(table: dict[str, Any]) -> LLMConfig:
    base = LLMConfig()
    return LLMConfig(
        enabled=bool(table.get("enabled", base.enabled)),
        provider=str(table.get("provider", base.provider)),
        model=str(table.get("model", base.model)),
        api_key_env=str(table.get("api_key_env", base.api_key_env)),
        max_tokens=int(table.get("max_tokens", base.max_tokens)),
        effort=Effort(str(table.get("effort", base.effort.value)).lower()),
        adaptive_thinking=bool(table.get("adaptive_thinking", base.adaptive_thinking)),
        timeout_seconds=float(table.get("timeout_seconds", base.timeout_seconds)),
        max_retries=int(table.get("max_retries", base.max_retries)),
        input_usd_per_mtok=float(
            table.get("input_usd_per_mtok", base.input_usd_per_mtok)
        ),
        output_usd_per_mtok=float(
            table.get("output_usd_per_mtok", base.output_usd_per_mtok)
        ),
    )


def _generation(table: dict[str, Any]) -> GenerationConfig:
    base = GenerationConfig()
    return GenerationConfig(
        use_call_graph=bool(table.get("use_call_graph", base.use_call_graph)),
        call_graph_max_depth=int(
            table.get("call_graph_max_depth", base.call_graph_max_depth)
        ),
        call_graph_max_callees=int(
            table.get("call_graph_max_callees", base.call_graph_max_callees)
        ),
        use_retrieval=bool(table.get("use_retrieval", base.use_retrieval)),
        retrieval_top_k=int(table.get("retrieval_top_k", base.retrieval_top_k)),
        embedding_dim=int(table.get("embedding_dim", base.embedding_dim)),
    )


def _sandbox(table: dict[str, Any]) -> SandboxConfig:
    base = SandboxConfig()
    return SandboxConfig(
        strategy=str(table.get("strategy", base.strategy)),
        max_parallel=int(table.get("max_parallel", base.max_parallel)),
        test_timeout_seconds=float(
            table.get("test_timeout_seconds", base.test_timeout_seconds)
        ),
        cpu_time_limit_seconds=int(
            table.get("cpu_time_limit_seconds", base.cpu_time_limit_seconds)
        ),
        memory_limit_mb=int(table.get("memory_limit_mb", base.memory_limit_mb)),
        detect_flakiness=bool(table.get("detect_flakiness", base.detect_flakiness)),
    )


def _mutation(table: dict[str, Any]) -> MutationConfig:
    base = MutationConfig()
    return MutationConfig(
        score_threshold=float(table.get("score_threshold", base.score_threshold)),
        max_mutants=int(table.get("max_mutants", base.max_mutants)),
        timeout_seconds=float(table.get("timeout_seconds", base.timeout_seconds)),
    )


def _orchestrator(table: dict[str, Any]) -> OrchestratorConfig:
    base = OrchestratorConfig()
    return OrchestratorConfig(
        max_targets=int(table.get("max_targets", base.max_targets)),
        max_wallclock_seconds=float(
            table.get("max_wallclock_seconds", base.max_wallclock_seconds)
        ),
        max_cost_usd=float(table.get("max_cost_usd", base.max_cost_usd)),
        max_tokens=int(table.get("max_tokens", base.max_tokens)),
        max_repair_attempts=int(
            table.get("max_repair_attempts", base.max_repair_attempts)
        ),
        max_strengthen_attempts=int(
            table.get("max_strengthen_attempts", base.max_strengthen_attempts)
        ),
        max_parallel_targets=int(
            table.get("max_parallel_targets", base.max_parallel_targets)
        ),
    )


def _storage(table: dict[str, Any]) -> StorageConfig:
    base = StorageConfig()
    return StorageConfig(
        backend=str(table.get("backend", base.backend)),
        root=Path(str(table.get("root", base.root))),
    )
