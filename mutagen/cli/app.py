"""CLI argument parsing and dispatch.

This module defines the command surface and wires a parsed invocation to the
composition root. It contains no domain behavior of its own.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from mutagen import __version__


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser.

    Returns:
        A configured :class:`argparse.ArgumentParser` with the ``run`` and
        ``report`` subcommands registered.
    """
    parser = argparse.ArgumentParser(
        prog="mutagen",
        description="Production-grade mutation testing for Python.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        help="Path to a Mutagen configuration file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Execute a mutation-testing run.")
    run.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override the minimum acceptable mutation score (0-1).",
    )

    subparsers.add_parser("report", help="Render the most recent run.")

    return parser


async def run_cli(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the selected command.

    Args:
        argv: Argument vector excluding the program name; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        A process exit code.
    """
    raise NotImplementedError
