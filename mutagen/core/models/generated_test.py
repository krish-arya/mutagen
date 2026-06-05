"""Generated-test domain model.

A :class:`GeneratedTest` is the artifact a
:class:`mutagen.core.interfaces.TestGenerator` produces for a
:class:`mutagen.core.models.target.Target`: synthesized test source plus the
metadata needed to write, run, and account for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mutagen.core.exceptions import ValidationError
from mutagen.core.models.cost import CostInfo


@dataclass(frozen=True, slots=True)
class GeneratedTest:
    """A synthesized test case awaiting validation.

    The test is not yet known to pass or to kill mutants; it is raw output
    from generation. The sandbox runner and mutation gate decide its fate.

    Attributes:
        test_id: Stable identifier, unique within a run.
        target_id: Identifier of the :class:`Target` this test exercises.
        module_path: Project-relative path where the test should be written
            (e.g. ``tests/test_generated_foo.py``).
        source: The complete, importable Python source of the test module.
        test_names: Names of the individual test functions defined in
            :attr:`source` (e.g. ``("test_handles_empty",)``).
        cost: Generation cost (tokens/currency) attributed to this test.
        imports: Extra import lines the test requires, for static assembly.
        is_valid: Whether the source passed syntax/AST/pytest validation. A
            test may be produced and returned even when invalid so the failure
            is visible downstream (e.g. for repair); only valid tests should be
            executed.
        validation_error: Human-readable reason the test is invalid, or empty
            when :attr:`is_valid` is ``True``.
    """

    test_id: str
    target_id: str
    module_path: str
    source: str
    test_names: tuple[str, ...] = field(default_factory=tuple)
    cost: CostInfo = field(default_factory=lambda: CostInfo())
    imports: tuple[str, ...] = field(default_factory=tuple)
    is_valid: bool = True
    validation_error: str = ""

    def validate(self) -> None:
        """Validate the generated test's *structural* invariants.

        This checks the dataclass is internally well-formed (non-empty ids,
        source, and at least one named test). It is distinct from the
        syntax/AST/pytest validation recorded in :attr:`is_valid`: a test can
        be structurally valid here yet have ``is_valid=False`` because its
        source failed to compile.

        Raises:
            ValidationError: If identifiers are blank, the source is empty,
                no test names are declared, the embedded cost is invalid, or
                an invalid test carries no explanatory error.
        """
        if not self.test_id.strip():
            raise ValidationError("GeneratedTest.test_id must be non-empty.")
        if not self.target_id.strip():
            raise ValidationError("GeneratedTest.target_id must be non-empty.")
        if not self.module_path.strip():
            raise ValidationError(
                "GeneratedTest.module_path must be non-empty."
            )
        if not self.source.strip():
            raise ValidationError("GeneratedTest.source must be non-empty.")
        if not self.test_names:
            raise ValidationError(
                "GeneratedTest.test_names must declare at least one test."
            )
        if not self.is_valid and not self.validation_error.strip():
            raise ValidationError(
                "Invalid GeneratedTest must carry a validation_error."
            )
        self.cost.validate()
