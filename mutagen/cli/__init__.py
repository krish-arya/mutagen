"""Command-line interface layer.

Translates command-line invocations into configuration and run requests,
delegating all work to the application services via the DI container.
"""

from mutagen.cli.app import build_parser, run_cli

__all__ = ["build_parser", "run_cli"]
