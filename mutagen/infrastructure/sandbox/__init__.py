"""Sandbox adapters implementing :class:`SandboxRunner`.

The :class:`SubprocessSandboxRunner` materializes generated tests into a
temporary directory and runs them under pytest (via ``pytest-json-report``) in
a hardened child process, with timeout and resource limits, twice over to
detect flakiness.
"""

from mutagen.infrastructure.sandbox.report_parser import (
    ReportParser,
    RunReport,
    TestVerdict,
)
from mutagen.infrastructure.sandbox.subprocess_runner import (
    SubprocessSandboxRunner,
)

__all__ = [
    "SubprocessSandboxRunner",
    "ReportParser",
    "RunReport",
    "TestVerdict",
]
