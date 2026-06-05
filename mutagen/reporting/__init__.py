"""Reporting layer.

Concrete :class:`mutagen.core.interfaces.Reporter` implementations that render
an enriched :class:`mutagen.core.models.run.RunReport`:

* :class:`MarkdownReporter` — human-readable ``report.md`` dashboard;
* :class:`JsonReporter` — machine-readable ``report.json``;
* :class:`TerminalReporter` — console dashboard (rich, with plain fallback);
* :class:`CompositeReporter` — fans out to several reporters at once.
"""

from mutagen.reporting.composite_reporter import CompositeReporter
from mutagen.reporting.json_reporter import JsonReporter
from mutagen.reporting.markdown_reporter import MarkdownReporter
from mutagen.reporting.terminal_reporter import TerminalReporter

__all__ = [
    "MarkdownReporter",
    "JsonReporter",
    "TerminalReporter",
    "CompositeReporter",
]
