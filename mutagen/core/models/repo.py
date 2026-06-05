"""Repository-context domain models.

A :class:`RepoContext` is the immutable snapshot of an ingested project that
every downstream stage (target selection, test generation, sandboxing) reads
from. It is produced by a :class:`mutagen.core.interfaces.RepoIngestor` and is
never mutated in place; ingestors build a new instance per run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mutagen.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class RepoContext:
    """An immutable snapshot of an ingested repository under analysis.

    This is the single source of truth about *what* is being tested: where the
    project lives, which files are source vs. test, the resolved Python
    version, and the commit it was taken at. Downstream stages must treat it as
    read-only.

    Attributes:
        root: Absolute path to the repository root on disk.
        source_files: Project-relative paths to source modules eligible for
            test generation. Always relative to :attr:`root`.
        test_files: Project-relative paths to existing test modules.
        python_version: Resolved interpreter version string (e.g. ``"3.11"``)
            the project targets, used to provision sandboxes.
        commit_sha: Full git commit SHA the snapshot was taken at, or ``None``
            if the project is not a git repository.
        import_root: Project-relative directory from which imports resolve
            (e.g. ``"src"``). Empty path means the repo root itself.
        metadata: Free-form, ingestor-supplied annotations (build system,
            detected frameworks, etc.). Keys and values are strings.
    """

    root: Path
    source_files: tuple[Path, ...] = field(default_factory=tuple)
    test_files: tuple[Path, ...] = field(default_factory=tuple)
    python_version: str = ""
    commit_sha: str | None = None
    import_root: Path = field(default_factory=Path)
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate internal consistency of the context.

        This checks only invariants that must hold regardless of filesystem
        state (it does not stat files). Use it as a cheap guard immediately
        after construction.

        Raises:
            ValidationError: If the root is not absolute, the import root is
                not relative, any source/test path is absolute, or the Python
                version is malformed.
        """
        if not self.root.is_absolute():
            raise ValidationError(
                f"RepoContext.root must be absolute, got {self.root!r}."
            )
        if self.import_root.is_absolute():
            raise ValidationError(
                "RepoContext.import_root must be repo-relative, got "
                f"{self.import_root!r}."
            )
        for label, paths in (
            ("source_files", self.source_files),
            ("test_files", self.test_files),
        ):
            for path in paths:
                if path.is_absolute():
                    raise ValidationError(
                        f"RepoContext.{label} entries must be repo-relative, "
                        f"got {path!r}."
                    )
        if self.python_version and not _is_version_like(self.python_version):
            raise ValidationError(
                f"RepoContext.python_version is malformed: {self.python_version!r}."
            )

    def resolve(self, relative: Path) -> Path:
        """Return the absolute on-disk path for a repo-relative ``relative``."""
        return self.root / relative


def _is_version_like(value: str) -> bool:
    """Whether ``value`` looks like a dotted version (e.g. ``3.11``/``3``)."""
    parts = value.split(".")
    return all(part.isdigit() for part in parts) and bool(parts)
