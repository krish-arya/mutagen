"""Filesystem- and git-backed :class:`RepoIngestor` adapter.

Acquires a repository from either a local path or a remote git URL into an
isolated working copy, provisions a per-repo virtualenv, installs detected
dependencies, discovers the test layout, and assembles a validated
:class:`RepoContext`.

The adapter never runs anything through a shell: every external command goes
through :class:`mutagen.infrastructure.process.CommandRunner`, which enforces
timeouts, retries, and structured logging. All heavyweight, host-touching
steps (clone, venv, install) are gated by :class:`IngestConfig` so they can be
disabled for fast or offline runs and bypassed entirely in tests.
"""

from __future__ import annotations

import shutil
import sys
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from mutagen.config.logging import get_logger
from mutagen.config.run_config import IngestConfig, RunConfig
from mutagen.core.exceptions import IngestionError
from mutagen.core.interfaces import RepoIngestor
from mutagen.core.models.repo import RepoContext
from mutagen.infrastructure.process import CommandError, CommandRunner, resolve_executable

_logger = get_logger(__name__)

# Directories never treated as source or test roots.
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "build",
        "dist",
        "node_modules",
    }
)

# Filename prefixes/globs that mark a Python file as a test.
_TEST_FILE_GLOBS = ("test_*.py", "*_test.py")

# Common directory names that hold tests.
_TEST_DIR_NAMES = frozenset({"tests", "test"})


class SourceKind(str, Enum):
    """Whether an ingest source is a local path or a remote git URL."""

    LOCAL = "local"
    GIT = "git"


@dataclass(frozen=True, slots=True)
class BuildSystem:
    """Detected dependency/build descriptors for a repository.

    Attributes:
        has_pyproject: Whether a ``pyproject.toml`` is present at the root.
        has_requirements: Whether a ``requirements.txt`` is present.
        has_setup_py: Whether a ``setup.py`` is present.
        requirements_files: Repo-relative paths to discovered requirements
            files (``requirements.txt`` and common variants).
    """

    has_pyproject: bool = False
    has_requirements: bool = False
    has_setup_py: bool = False
    requirements_files: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def is_installable(self) -> bool:
        """Whether any recognized dependency source was found."""
        return (
            self.has_pyproject or self.has_requirements or self.has_setup_py
        )


@dataclass(frozen=True, slots=True)
class TestLayout:
    """Detected test configuration and locations.

    Attributes:
        uses_pytest: Whether a pytest configuration was detected.
        test_dirs: Repo-relative directories that contain tests.
        test_files: Repo-relative paths to individual test modules.
    """

    uses_pytest: bool = False
    test_dirs: tuple[Path, ...] = field(default_factory=tuple)
    test_files: tuple[Path, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class FilesystemRepoIngestor(RepoIngestor):
    """Ingests a repository from a local path or git URL.

    Args:
        config: The run configuration; only its :attr:`RunConfig.ingest`
            section is consulted.
        runner: Subprocess runner used for git/venv/pip. Injected for testing;
            when ``None`` a default runner is built from the ingest config.
    """

    config: RunConfig
    runner: CommandRunner | None = None

    def __post_init__(self) -> None:
        if self.runner is None:
            ic = self.config.ingest
            self.runner = CommandRunner(
                default_timeout_seconds=ic.command_timeout_seconds,
                max_retries=ic.max_retries,
                retry_backoff_seconds=ic.retry_backoff_seconds,
            )

    @property
    def _ingest_config(self) -> IngestConfig:
        return self.config.ingest

    @property
    def _runner(self) -> CommandRunner:
        assert self.runner is not None  # established in __post_init__
        return self.runner

    async def ingest(self, source: str | Path) -> RepoContext:
        """Ingest ``source`` into a validated :class:`RepoContext`.

        Steps: detect source kind, acquire into an isolated workspace
        (clone or copy), detect the build system, create a venv and install
        dependencies (both gated by config), detect the test layout, capture
        the commit, and assemble the context.

        Args:
            source: A local path or a remote git URL.

        Returns:
            A validated :class:`RepoContext` rooted in the isolated workspace.

        Raises:
            IngestionError: If acquisition, provisioning, or assembly fails.
        """
        kind = self.classify_source(source)
        workspace = self._create_workspace()
        _logger.info(
            "ingest started",
            extra={"context": {"source": str(source), "kind": kind.value,
                               "workspace": str(workspace)}},
        )

        try:
            repo_root = await self._acquire(source, kind, workspace)

            build_system = self.detect_build_system(repo_root)
            metadata: dict[str, str] = {
                "source": str(source),
                "source_kind": kind.value,
                "has_pyproject": str(build_system.has_pyproject).lower(),
                "has_requirements": str(build_system.has_requirements).lower(),
                "has_setup_py": str(build_system.has_setup_py).lower(),
            }

            venv_python: Path | None = None
            if self._ingest_config.create_venv:
                venv_python = await self._create_venv(repo_root)
                metadata["venv"] = str(venv_python)
                if self._ingest_config.install_deps and build_system.is_installable:
                    await self._install_dependencies(
                        repo_root, venv_python, build_system
                    )
                    metadata["deps_installed"] = "true"

            layout = self.detect_test_layout(repo_root)
            metadata["uses_pytest"] = str(layout.uses_pytest).lower()

            commit_sha = await self._capture_commit(repo_root)
            import_root = self._detect_import_root(repo_root)

            context = self._build_context(
                repo_root=repo_root,
                build_system=build_system,
                layout=layout,
                commit_sha=commit_sha,
                import_root=import_root,
                metadata=metadata,
            )
            context.validate()
            _logger.info(
                "ingest completed",
                extra={"context": {"root": str(repo_root),
                                   "source_files": len(context.source_files),
                                   "test_files": len(context.test_files),
                                   "commit": commit_sha}},
            )
            return context
        except IngestionError:
            self._cleanup_workspace(workspace)
            raise
        except Exception as exc:  # defensive: never leak partial workspaces
            self._cleanup_workspace(workspace)
            raise IngestionError(f"Ingestion failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Source classification & acquisition
    # ------------------------------------------------------------------ #

    @staticmethod
    def classify_source(source: str | Path) -> SourceKind:
        """Classify ``source`` as a local path or a remote git URL.

        A source is treated as git when it uses a recognized VCS scheme
        (``http(s)://``, ``git://``, ``ssh://``) or the ``user@host:path``
        SCP-like form, *and* it does not point at an existing local path.

        Args:
            source: The ingest source.

        Returns:
            The detected :class:`SourceKind`.
        """
        if isinstance(source, Path):
            return SourceKind.LOCAL

        text = source.strip()
        if Path(text).exists():
            return SourceKind.LOCAL
        if text.endswith(".git"):
            return SourceKind.GIT
        if "://" in text and text.split("://", 1)[0] in {
            "http",
            "https",
            "git",
            "ssh",
        }:
            return SourceKind.GIT
        # SCP-like syntax: git@github.com:org/repo
        if "@" in text and ":" in text.split("@", 1)[1] and "/" in text:
            return SourceKind.GIT
        return SourceKind.LOCAL

    async def _acquire(
        self, source: str | Path, kind: SourceKind, workspace: Path
    ) -> Path:
        """Acquire the repository into ``workspace`` and return its root."""
        if kind is SourceKind.GIT:
            return await self._clone(str(source), workspace)
        return self._copy_local(Path(source), workspace)

    async def _clone(self, url: str, workspace: Path) -> Path:
        """Clone ``url`` into the workspace (shallow unless configured)."""
        git = resolve_executable("git")
        dest = workspace / "repo"
        args = [git, "clone"]
        depth = self._ingest_config.clone_depth
        if depth > 0:
            args += ["--depth", str(depth)]
        args += [url, str(dest)]
        # Cloning is network I/O: allow it to retry.
        await self._runner.run(args, retries=self._ingest_config.max_retries)
        return dest

    def _copy_local(self, src: Path, workspace: Path) -> Path:
        """Copy a local repository into the isolated workspace."""
        resolved = src.expanduser().resolve()
        if not resolved.exists():
            raise IngestionError(f"Local source does not exist: {resolved}.")
        if not resolved.is_dir():
            raise IngestionError(f"Local source is not a directory: {resolved}.")
        dest = workspace / "repo"
        try:
            shutil.copytree(
                resolved,
                dest,
                ignore=shutil.ignore_patterns(*_IGNORED_DIRS),
                symlinks=True,
            )
        except OSError as exc:
            raise IngestionError(f"Failed to copy local source: {exc}") from exc
        return dest

    # ------------------------------------------------------------------ #
    # Workspace management
    # ------------------------------------------------------------------ #

    def _create_workspace(self) -> Path:
        """Create a fresh isolated working directory and return it."""
        base = self._ingest_config.workspace_root.expanduser().resolve()
        workspace = base / f"ingest-{uuid.uuid4().hex[:12]}"
        try:
            workspace.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise IngestionError(
                f"Failed to create workspace {workspace}: {exc}"
            ) from exc
        return workspace

    def _cleanup_workspace(self, workspace: Path) -> None:
        """Best-effort removal of a workspace after a failure."""
        shutil.rmtree(workspace, ignore_errors=True)
        _logger.debug(
            "workspace cleaned up",
            extra={"context": {"workspace": str(workspace)}},
        )

    # ------------------------------------------------------------------ #
    # Build-system & test detection
    # ------------------------------------------------------------------ #

    @staticmethod
    def detect_build_system(repo_root: Path) -> BuildSystem:
        """Detect dependency descriptors at ``repo_root``.

        Args:
            repo_root: The repository root to inspect.

        Returns:
            A :class:`BuildSystem` describing what was found.
        """
        has_pyproject = (repo_root / "pyproject.toml").is_file()
        has_setup_py = (repo_root / "setup.py").is_file()

        requirements: list[Path] = []
        for candidate in ("requirements.txt", "requirements-dev.txt",
                          "requirements/dev.txt", "requirements/base.txt"):
            if (repo_root / candidate).is_file():
                requirements.append(Path(candidate))

        return BuildSystem(
            has_pyproject=has_pyproject,
            has_requirements=bool(requirements),
            has_setup_py=has_setup_py,
            requirements_files=tuple(requirements),
        )

    @classmethod
    def detect_test_layout(cls, repo_root: Path) -> TestLayout:
        """Detect pytest configuration and test locations under ``repo_root``.

        pytest is considered configured if a ``pytest.ini``/``tox.ini`` exists,
        or ``pyproject.toml``/``setup.cfg`` mention pytest, or any test files
        are present.

        Args:
            repo_root: The repository root to inspect.

        Returns:
            A :class:`TestLayout` describing the detected setup.
        """
        test_files = cls._find_test_files(repo_root)
        test_dirs = cls._find_test_dirs(repo_root, test_files)
        uses_pytest = cls._detect_pytest(repo_root) or bool(test_files)
        return TestLayout(
            uses_pytest=uses_pytest,
            test_dirs=tuple(sorted(test_dirs)),
            test_files=tuple(sorted(test_files)),
        )

    @staticmethod
    def _detect_pytest(repo_root: Path) -> bool:
        """Whether pytest is configured via a config file marker."""
        if (repo_root / "pytest.ini").is_file():
            return True
        for name in ("pyproject.toml", "setup.cfg", "tox.ini"):
            path = repo_root / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "pytest" in text or "[tool:pytest]" in text:
                return True
        return False

    @classmethod
    def _find_test_files(cls, repo_root: Path) -> list[Path]:
        """Return repo-relative paths to all test modules."""
        seen: set[Path] = set()
        for pattern in _TEST_FILE_GLOBS:
            for path in repo_root.rglob(pattern):
                if not path.is_file():
                    continue
                if cls._is_ignored(path.relative_to(repo_root)):
                    continue
                seen.add(path.relative_to(repo_root))
        return sorted(seen)

    @classmethod
    def _find_test_dirs(
        cls, repo_root: Path, test_files: list[Path]
    ) -> set[Path]:
        """Infer test directories from named dirs and test-file locations."""
        dirs: set[Path] = set()
        for name in _TEST_DIR_NAMES:
            candidate = repo_root / name
            if candidate.is_dir():
                dirs.add(Path(name))
        for rel in test_files:
            if rel.parent != Path("."):
                dirs.add(rel.parent)
        return dirs

    @staticmethod
    def _is_ignored(relative: Path) -> bool:
        """Whether a repo-relative path lives under an ignored directory."""
        return any(part in _IGNORED_DIRS for part in relative.parts)

    # ------------------------------------------------------------------ #
    # Virtualenv & dependency install
    # ------------------------------------------------------------------ #

    async def _create_venv(self, repo_root: Path) -> Path:
        """Create a virtualenv under ``repo_root`` and return its interpreter."""
        venv_dir = repo_root / ".venv"
        await self._runner.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            retries=0,
        )
        python = self._venv_python(venv_dir)
        if not python.exists():
            raise IngestionError(
                f"Virtualenv interpreter not found after creation: {python}."
            )
        return python

    @staticmethod
    def _venv_python(venv_dir: Path) -> Path:
        """Return the interpreter path for a venv on the current platform."""
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    async def _install_dependencies(
        self, repo_root: Path, python: Path, build_system: BuildSystem
    ) -> None:
        """Install detected dependencies into the venv.

        Prefers an editable install of the project itself when a
        ``pyproject.toml`` or ``setup.py`` is present; otherwise installs from
        the discovered requirements files. Network-bound, so retried.
        """
        extra = list(self._ingest_config.pip_extra_args)
        retries = self._ingest_config.max_retries

        if build_system.has_pyproject or build_system.has_setup_py:
            await self._runner.run(
                [str(python), "-m", "pip", "install", "-e", ".", *extra],
                cwd=repo_root,
                retries=retries,
            )
        for req in build_system.requirements_files:
            await self._runner.run(
                [str(python), "-m", "pip", "install", "-r", str(req), *extra],
                cwd=repo_root,
                retries=retries,
            )

    # ------------------------------------------------------------------ #
    # VCS metadata & context assembly
    # ------------------------------------------------------------------ #

    async def _capture_commit(self, repo_root: Path) -> str | None:
        """Return the HEAD commit SHA, or ``None`` if not a git repo."""
        if not (repo_root / ".git").exists():
            return None
        try:
            git = resolve_executable("git")
        except CommandError:
            return None
        try:
            result = await self._runner.run(
                [git, "rev-parse", "HEAD"],
                cwd=repo_root,
                retries=0,
                check=True,
            )
        except CommandError:
            return None
        sha = result.stdout.strip()
        return sha or None

    def _detect_import_root(self, repo_root: Path) -> Path:
        """Detect the import root (``src`` layout vs. flat)."""
        if (repo_root / "src").is_dir():
            return Path("src")
        return Path()

    def _build_context(
        self,
        *,
        repo_root: Path,
        build_system: BuildSystem,
        layout: TestLayout,
        commit_sha: str | None,
        import_root: Path,
        metadata: dict[str, str],
    ) -> RepoContext:
        """Assemble the :class:`RepoContext` from gathered facts."""
        source_files = self._find_source_files(
            repo_root, import_root, set(layout.test_files)
        )
        return RepoContext(
            root=repo_root,
            source_files=source_files,
            test_files=layout.test_files,
            python_version=self._resolve_python_version(),
            commit_sha=commit_sha,
            import_root=import_root,
            metadata=metadata,
        )

    @classmethod
    def _find_source_files(
        cls, repo_root: Path, import_root: Path, test_files: set[Path]
    ) -> tuple[Path, ...]:
        """Return repo-relative non-test Python modules under the import root."""
        search_base = repo_root / import_root
        if not search_base.is_dir():
            search_base = repo_root
        found: list[Path] = []
        for path in search_base.rglob("*.py"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root)
            if cls._is_ignored(rel) or rel in test_files:
                continue
            if cls._looks_like_test(rel):
                continue
            found.append(rel)
        return tuple(sorted(found))

    @staticmethod
    def _looks_like_test(relative: Path) -> bool:
        """Whether a path is a test module by name or directory."""
        name = relative.name
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
        return any(part in _TEST_DIR_NAMES for part in relative.parts)

    @staticmethod
    def _resolve_python_version() -> str:
        """Resolve the running interpreter's ``major.minor`` version."""
        return f"{sys.version_info.major}.{sys.version_info.minor}"
