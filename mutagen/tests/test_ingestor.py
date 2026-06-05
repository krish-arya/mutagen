"""Tests for :class:`FilesystemRepoIngestor`.

External commands (git, venv, pip) are stubbed via a :class:`FakeRunner` so
the suite never touches the network or builds real environments. Filesystem
acquisition (local copy) and all detection logic run for real against
fixtures materialized in ``tmp_path``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mutagen.config.run_config import IngestConfig, RunConfig
from mutagen.core.exceptions import IngestionError
from mutagen.infrastructure.ingest import (
    BuildSystem,
    FilesystemRepoIngestor,
    SourceKind,
)
from mutagen.infrastructure.process import CommandError, CommandResult


class FakeRunner:
    """A drop-in :class:`CommandRunner` substitute that records calls.

    By default every command "succeeds" with empty output. Specific argv
    prefixes can be mapped to scripted results or exceptions, and a side effect
    (e.g. creating a venv interpreter file) can run when a command matches.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._results: dict[tuple[str, ...], CommandResult] = {}
        self._errors: dict[tuple[str, ...], CommandError] = {}
        self._side_effects: dict[tuple[str, ...], object] = {}

    def on(
        self,
        prefix: Sequence[str],
        *,
        result: CommandResult | None = None,
        error: CommandError | None = None,
        side_effect: object | None = None,
    ) -> None:
        key = tuple(prefix)
        if result is not None:
            self._results[key] = result
        if error is not None:
            self._errors[key] = error
        if side_effect is not None:
            self._side_effects[key] = side_effect

    def _match(self, argv: tuple[str, ...], table: dict) -> object | None:
        for key, value in table.items():
            if argv[: len(key)] == key or any(
                argv[i : i + len(key)] == key
                for i in range(len(argv) - len(key) + 1)
            ):
                return value
        return None

    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: object | None = None,
        timeout_seconds: float | None = None,
        retries: int | None = None,
        check: bool = True,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)

        error = self._match(argv, self._errors)
        if isinstance(error, CommandError):
            raise error

        effect = self._match(argv, self._side_effects)
        if callable(effect):
            effect(argv, cwd)

        result = self._match(argv, self._results)
        if isinstance(result, CommandResult):
            return result
        return CommandResult(
            args=argv, returncode=0, stdout="", stderr="", duration_seconds=0.0
        )

    def ran(self, needle: str) -> bool:
        """Whether any recorded call contained ``needle`` as an argument."""
        return any(needle in argv for argv in self.calls)


def _make_config(tmp_path: Path, **ingest_kwargs: object) -> RunConfig:
    ingest = IngestConfig(
        workspace_root=tmp_path / "workspaces",
        retry_backoff_seconds=0.0,
        **ingest_kwargs,  # type: ignore[arg-type]
    )
    return RunConfig(project_root=tmp_path, ingest=ingest)


def _make_ingestor(
    tmp_path: Path, runner: FakeRunner, **ingest_kwargs: object
) -> FilesystemRepoIngestor:
    config = _make_config(tmp_path, **ingest_kwargs)
    return FilesystemRepoIngestor(config=config, runner=runner)  # type: ignore[arg-type]


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A flat-layout repo with src, tests, and a pyproject."""
    repo = tmp_path / "sample"
    _write(repo / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(repo / "requirements.txt", "pytest\n")
    _write(repo / "pkg" / "__init__.py")
    _write(repo / "pkg" / "core.py", "def f():\n    return 1\n")
    _write(repo / "tests" / "test_core.py", "def test_f():\n    assert True\n")
    return repo


# ---------------------------------------------------------------------- #
# Source classification
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source,expected",
    [
        ("https://github.com/org/repo", SourceKind.GIT),
        ("https://github.com/org/repo.git", SourceKind.GIT),
        ("git@github.com:org/repo.git", SourceKind.GIT),
        ("git://example.com/repo.git", SourceKind.GIT),
        ("ssh://git@example.com/repo", SourceKind.GIT),
    ],
)
def test_classify_git_sources(source: str, expected: SourceKind) -> None:
    assert FilesystemRepoIngestor.classify_source(source) is expected


def test_classify_existing_local_path_is_local(tmp_path: Path) -> None:
    assert (
        FilesystemRepoIngestor.classify_source(tmp_path) is SourceKind.LOCAL
    )
    assert (
        FilesystemRepoIngestor.classify_source(str(tmp_path))
        is SourceKind.LOCAL
    )


def test_classify_nonexistent_plain_path_is_local() -> None:
    assert (
        FilesystemRepoIngestor.classify_source("./some/local/dir")
        is SourceKind.LOCAL
    )


# ---------------------------------------------------------------------- #
# Build-system & test detection
# ---------------------------------------------------------------------- #


def test_detect_build_system(sample_repo: Path) -> None:
    bs = FilesystemRepoIngestor.detect_build_system(sample_repo)
    assert bs.has_pyproject
    assert bs.has_requirements
    assert not bs.has_setup_py
    assert bs.is_installable
    assert Path("requirements.txt") in bs.requirements_files


def test_detect_build_system_empty(tmp_path: Path) -> None:
    bs = FilesystemRepoIngestor.detect_build_system(tmp_path)
    assert not bs.is_installable


def test_detect_test_layout(sample_repo: Path) -> None:
    layout = FilesystemRepoIngestor.detect_test_layout(sample_repo)
    assert layout.uses_pytest
    assert Path("tests/test_core.py") in layout.test_files
    assert Path("tests") in layout.test_dirs


def test_detect_pytest_via_pytest_ini(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\n")
    layout = FilesystemRepoIngestor.detect_test_layout(tmp_path)
    assert layout.uses_pytest


def test_detection_ignores_venv_dirs(tmp_path: Path) -> None:
    _write(tmp_path / ".venv" / "lib" / "test_vendored.py", "")
    _write(tmp_path / "tests" / "test_real.py", "")
    layout = FilesystemRepoIngestor.detect_test_layout(tmp_path)
    assert Path("tests/test_real.py") in layout.test_files
    assert all(".venv" not in p.parts for p in layout.test_files)


# ---------------------------------------------------------------------- #
# Full ingest: local copy + isolation
# ---------------------------------------------------------------------- #


def _venv_side_effect(argv: tuple[str, ...], cwd: Path | None) -> None:
    """Materialize a fake venv interpreter when `python -m venv` is called."""
    venv_dir = Path(argv[-1])
    import sys as _sys

    if _sys.platform == "win32":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")


async def test_ingest_local_copies_into_isolated_workspace(
    sample_repo: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    runner.on(["-m", "venv"], side_effect=_venv_side_effect)
    ingestor = _make_ingestor(tmp_path, runner)

    ctx = await ingestor.ingest(sample_repo)

    # Root is inside the isolated workspace, not the original source.
    assert ctx.root != sample_repo
    assert (tmp_path / "workspaces") in ctx.root.parents
    assert (ctx.root / "pkg" / "core.py").is_file()
    # Original is untouched.
    assert (sample_repo / "pkg" / "core.py").is_file()


async def test_ingest_builds_valid_context(
    sample_repo: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    runner.on(["-m", "venv"], side_effect=_venv_side_effect)
    ingestor = _make_ingestor(tmp_path, runner)

    ctx = await ingestor.ingest(sample_repo)

    ctx.validate()  # must not raise
    assert Path("pkg/core.py") in ctx.source_files
    assert Path("tests/test_core.py") in ctx.test_files
    # Test files are never classified as source.
    assert Path("tests/test_core.py") not in ctx.source_files
    assert ctx.metadata["uses_pytest"] == "true"
    assert ctx.metadata["has_pyproject"] == "true"


async def test_ingest_detects_src_layout_import_root(tmp_path: Path) -> None:
    repo = tmp_path / "srcrepo"
    _write(repo / "src" / "pkg" / "__init__.py")
    _write(repo / "src" / "pkg" / "mod.py", "x = 1\n")
    runner = FakeRunner()
    ingestor = _make_ingestor(tmp_path, runner, create_venv=False)

    ctx = await ingestor.ingest(repo)

    assert ctx.import_root == Path("src")
    assert Path("src/pkg/mod.py") in ctx.source_files


# ---------------------------------------------------------------------- #
# Venv / install gating
# ---------------------------------------------------------------------- #


async def test_venv_and_install_skipped_when_disabled(
    sample_repo: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    ingestor = _make_ingestor(
        tmp_path, runner, create_venv=False, install_deps=False
    )

    await ingestor.ingest(sample_repo)

    assert not runner.ran("venv")
    assert not runner.ran("pip")


async def test_install_runs_editable_and_requirements(
    sample_repo: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    runner.on(["-m", "venv"], side_effect=_venv_side_effect)
    ingestor = _make_ingestor(tmp_path, runner)

    await ingestor.ingest(sample_repo)

    assert runner.ran("venv")
    # Editable install (pyproject present) and requirements install both happen.
    assert any("install" in c and "-e" in c for c in runner.calls)
    assert any("install" in c and "-r" in c for c in runner.calls)


async def test_install_skipped_when_no_build_system(tmp_path: Path) -> None:
    repo = tmp_path / "bare"
    _write(repo / "pkg" / "mod.py", "x = 1\n")
    runner = FakeRunner()
    runner.on(["-m", "venv"], side_effect=_venv_side_effect)
    ingestor = _make_ingestor(tmp_path, runner)

    await ingestor.ingest(repo)

    assert runner.ran("venv")  # venv still created
    assert not runner.ran("pip")  # but nothing to install


# ---------------------------------------------------------------------- #
# Clone path (git source)
# ---------------------------------------------------------------------- #


async def test_ingest_git_source_clones(tmp_path: Path) -> None:
    runner = FakeRunner()

    def clone_effect(argv: tuple[str, ...], cwd: Path | None) -> None:
        # The clone destination is the final argv element.
        dest = Path(argv[-1])
        _write(dest / "pyproject.toml", "")
        _write(dest / "pkg" / "mod.py", "x = 1\n")

    runner.on(["clone"], side_effect=clone_effect)
    runner.on(["-m", "venv"], side_effect=_venv_side_effect)
    # rev-parse returns a fake SHA; .git won't exist, so commit stays None.
    ingestor = _make_ingestor(tmp_path, runner, create_venv=False)

    ctx = await ingestor.ingest("https://github.com/org/repo.git")

    assert runner.ran("clone")
    assert any("--depth" in c for c in runner.calls)  # shallow by default
    assert Path("pkg/mod.py") in ctx.source_files


# ---------------------------------------------------------------------- #
# Failure handling & cleanup
# ---------------------------------------------------------------------- #


async def test_missing_local_source_raises_and_cleans_up(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    ingestor = _make_ingestor(tmp_path, runner, create_venv=False)

    with pytest.raises(IngestionError):
        await ingestor.ingest(tmp_path / "does-not-exist")

    # Workspace dir should have been removed on failure.
    workspaces = tmp_path / "workspaces"
    leftovers = list(workspaces.iterdir()) if workspaces.exists() else []
    assert leftovers == []


async def test_clone_failure_propagates_as_ingestion_error(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.on(["clone"], error=CommandError("network down"))
    ingestor = _make_ingestor(tmp_path, runner, create_venv=False)

    with pytest.raises(IngestionError):
        await ingestor.ingest("https://github.com/org/repo.git")
