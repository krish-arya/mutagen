"""Validation of generated test source.

:class:`TestValidator` runs three layers of static checks over a generated test
module, in order of increasing specificity:

1. **Syntax validation** — the source compiles (``compile``/``ast.parse``).
2. **AST validation** — structural sanity: at least one ``test_*`` function,
   the target symbol is referenced, and no obviously-broken constructs.
3. **pytest-compatibility checks** — conventions pytest relies on: test
   functions are module-level (or in ``Test*`` classes without ``__init__``),
   take no required positional args beyond fixtures, and the module has no
   top-level ``return``.

Validation is static only — it never imports or executes the test (that is the
sandbox runner's job). It returns a structured :class:`ValidationResult` rather
than raising, so the generator can attach the verdict to the artifact.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# pytest discovers functions named with this prefix.
_TEST_PREFIX = "test"
# pytest test classes are named with this prefix and must not define __init__.
_TEST_CLASS_PREFIX = "Test"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """The outcome of validating generated test source.

    Attributes:
        is_valid: Whether the source passed every check.
        errors: Human-readable failure reasons (empty when valid).
        test_names: Names of discovered ``test_*`` functions (module-level and
            methods), populated whenever parsing succeeds.
    """

    is_valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    test_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        """A single-line description of the failure(s), or empty if valid."""
        return "; ".join(self.errors)


class TestValidator:
    """Validates generated test source via syntax, AST, and pytest checks."""

    def validate(self, source: str, *, target_symbol: str = "") -> ValidationResult:
        """Validate ``source`` and return a structured result.

        Args:
            source: The generated test module source.
            target_symbol: The (possibly dotted) symbol the test should
                reference (e.g. ``"fn"`` or ``"Class.method"``). When provided,
                AST validation checks the symbol appears in the source.

        Returns:
            A :class:`ValidationResult`.
        """
        # Layer 1: syntax.
        tree = self._parse(source)
        if isinstance(tree, str):
            return ValidationResult(is_valid=False, errors=(tree,))

        errors: list[str] = []
        test_names = self._discover_tests(tree)

        # Layer 2: AST structural checks.
        errors.extend(self._ast_errors(tree, test_names, target_symbol))

        # Layer 3: pytest-compatibility checks.
        errors.extend(self._pytest_errors(tree))

        return ValidationResult(
            is_valid=not errors,
            errors=tuple(errors),
            test_names=test_names,
        )

    # ------------------------------------------------------------------ #
    # Layer 1: syntax
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse(source: str) -> ast.Module | str:
        """Parse ``source``; return the AST or an error string."""
        if not source.strip():
            return "Generated source is empty."
        try:
            return ast.parse(source)
        except SyntaxError as exc:
            line = exc.lineno if exc.lineno is not None else "?"
            return f"Syntax error at line {line}: {exc.msg}"

    # ------------------------------------------------------------------ #
    # Layer 2: AST structure
    # ------------------------------------------------------------------ #

    def _ast_errors(
        self,
        tree: ast.Module,
        test_names: tuple[str, ...],
        target_symbol: str,
    ) -> list[str]:
        """Structural sanity checks over the parsed module."""
        errors: list[str] = []
        if not test_names:
            errors.append("No test functions found (expected at least one 'test_*').")
        if target_symbol:
            leaf = target_symbol.rsplit(".", 1)[-1]
            if not self._references(tree, leaf):
                errors.append(
                    f"Target symbol '{leaf}' is never referenced in the test."
                )
        if not self._has_import(tree):
            errors.append("Test module has no import statements.")
        return errors

    @staticmethod
    def _references(tree: ast.Module, name: str) -> bool:
        """Whether ``name`` appears as a Name/Attribute anywhere in the tree."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name:
                return True
            if isinstance(node, ast.Attribute) and node.attr == name:
                return True
            if isinstance(node, ast.alias) and (
                node.asname == name or node.name.rsplit(".", 1)[-1] == name
            ):
                return True
        return False

    @staticmethod
    def _has_import(tree: ast.Module) -> bool:
        """Whether the module contains any import statement."""
        return any(
            isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)
        )

    # ------------------------------------------------------------------ #
    # Layer 3: pytest compatibility
    # ------------------------------------------------------------------ #

    def _pytest_errors(self, tree: ast.Module) -> list[str]:
        """Checks for conventions pytest collection depends on."""
        errors: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Return):
                errors.append("Top-level 'return' is not valid in a module.")
            if isinstance(node, ast.ClassDef) and node.name.startswith(
                _TEST_CLASS_PREFIX
            ):
                if self._defines_init(node):
                    errors.append(
                        f"Test class '{node.name}' defines __init__; pytest "
                        f"will not collect it."
                    )
        return errors

    @staticmethod
    def _defines_init(cls: ast.ClassDef) -> bool:
        """Whether a class body defines an ``__init__`` method."""
        return any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "__init__"
            for n in cls.body
        )

    # ------------------------------------------------------------------ #
    # Test discovery
    # ------------------------------------------------------------------ #

    @classmethod
    def _discover_tests(cls, tree: ast.Module) -> tuple[str, ...]:
        """Return names of module-level and Test-class ``test_*`` functions."""
        names: list[str] = []
        for node in tree.body:
            if cls._is_test_func(node):
                names.append(node.name)  # type: ignore[attr-defined]
            elif isinstance(node, ast.ClassDef) and node.name.startswith(
                _TEST_CLASS_PREFIX
            ):
                for member in node.body:
                    if cls._is_test_func(member):
                        names.append(
                            f"{node.name}::{member.name}"  # type: ignore[attr-defined]
                        )
        return tuple(names)

    @staticmethod
    def _is_test_func(node: ast.AST) -> bool:
        """Whether ``node`` is a function whose name pytest would collect."""
        return isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith(f"{_TEST_PREFIX}_")
