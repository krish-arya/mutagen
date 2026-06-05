"""Tests for :class:`FunctionExtractor`.

Pure AST parsing: these verify name qualification, kind classification, body
line and statement counting (docstring-aware), decorator rendering, and error
handling, all from in-memory source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutagen.core.models.target import TargetKind
from mutagen.infrastructure.selection import (
    ExtractionError,
    FunctionExtractor,
)


@pytest.fixture
def extractor() -> FunctionExtractor:
    return FunctionExtractor()


def _by_name(funcs, name):  # type: ignore[no-untyped-def]
    return next(f for f in funcs if f.qualified_name == name)


def test_extracts_free_function(extractor: FunctionExtractor) -> None:
    funcs = extractor.extract_source("def f(x):\n    return x + 1\n")
    assert len(funcs) == 1
    assert funcs[0].qualified_name == "f"
    assert funcs[0].kind is TargetKind.FUNCTION
    assert funcs[0].statement_count == 1


def test_classifies_methods(extractor: FunctionExtractor) -> None:
    src = "class C:\n    def m(self):\n        return 1\n"
    funcs = extractor.extract_source(src)
    assert _by_name(funcs, "C.m").kind is TargetKind.METHOD


def test_nested_function_qualname(extractor: FunctionExtractor) -> None:
    src = "def outer():\n    def inner():\n        return 2\n    return inner\n"
    names = {f.qualified_name for f in extractor.extract_source(src)}
    assert "outer" in names
    assert "outer.<locals>.inner" in names


def test_docstring_excluded_from_body_and_count(
    extractor: FunctionExtractor,
) -> None:
    src = 'def f():\n    """Doc."""\n    x = 1\n    return x\n'
    func = extractor.extract_source(src)[0]
    # Docstring line 2 must not count as a body line.
    assert 2 not in func.body_lines
    assert func.body_lines == frozenset({3, 4})
    assert func.statement_count == 2


def test_statement_count_recurses_into_blocks(
    extractor: FunctionExtractor,
) -> None:
    src = (
        "def f(n):\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total += i\n"
        "    return total\n"
    )
    func = extractor.extract_source(src)[0]
    # assign, for, aug-assign, return == 4 statements.
    assert func.statement_count == 4


def test_decorator_names_rendered(extractor: FunctionExtractor) -> None:
    src = (
        "class C:\n"
        "    @property\n"
        "    def p(self):\n"
        "        return self._x\n"
        "    @staticmethod\n"
        "    def s():\n"
        "        return 1\n"
    )
    funcs = extractor.extract_source(src)
    prop = _by_name(funcs, "C.p")
    assert prop.decorators == ("property",)
    assert prop.is_property
    assert _by_name(funcs, "C.s").decorators == ("staticmethod",)


def test_dotted_and_called_decorators(extractor: FunctionExtractor) -> None:
    src = (
        "import functools\n"
        "class C:\n"
        "    @functools.lru_cache(maxsize=1)\n"
        "    def m(self):\n"
        "        return 1\n"
    )
    func = _by_name(extractor.extract_source(src), "C.m")
    assert func.decorators == ("functools.lru_cache",)


def test_async_function_flagged(extractor: FunctionExtractor) -> None:
    func = extractor.extract_source("async def f():\n    return 1\n")[0]
    assert func.is_async


def test_span_lines(extractor: FunctionExtractor) -> None:
    src = "def f():\n    x = 1\n    return x\n"
    func = extractor.extract_source(src)[0]
    assert func.start_line == 1
    assert func.end_line == 3


def test_syntax_error_raises(extractor: FunctionExtractor) -> None:
    with pytest.raises(ExtractionError):
        extractor.extract_source("def f(:\n    pass\n")


def test_extract_file_reads_source(
    extractor: FunctionExtractor, tmp_path: Path
) -> None:
    path = tmp_path / "m.py"
    path.write_text("def g():\n    return 0\n", encoding="utf-8")
    funcs = extractor.extract_file(path)
    assert funcs[0].qualified_name == "g"


def test_extract_missing_file_raises(extractor: FunctionExtractor) -> None:
    with pytest.raises(ExtractionError):
        extractor.extract_file(Path("nope/does-not-exist.py"))
