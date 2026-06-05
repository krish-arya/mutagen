"""Mutation-target domain models.

A target describes a region of source code that is eligible for mutation,
along with the module that contains it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mutagen.core.models.location import SourceSpan


@dataclass(frozen=True, slots=True)
class TargetModule:
    """A source module under test.

    Attributes:
        path: Path to the module's source file.
        qualified_name: Dotted import path (e.g. ``pkg.subpkg.module``).
    """

    path: Path
    qualified_name: str


@dataclass(frozen=True, slots=True)
class MutationTarget:
    """A specific, mutable region within a module.

    A target binds a span of source to the AST node kind that occupies it,
    so that operators can decide whether they apply.

    Attributes:
        module: The module that contains this target.
        span: The source region eligible for mutation.
        node_type: AST node category (e.g. ``"BinOp"``, ``"Compare"``).
        identifier: Stable, content-derived id for deduplication.
    """

    module: TargetModule
    span: SourceSpan
    node_type: str
    identifier: str = field(default="")
