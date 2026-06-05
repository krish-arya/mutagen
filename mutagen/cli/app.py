"""CLI argument parsing and dispatch.

Defines the command surface (``mutagen run <repo>``, ``mutagen report``) and
wires a parsed invocation to the composition root: it loads configuration,
configures structured logging, builds the :class:`Container`, and drives the
orchestrator with a live Rich progress UI, finishing with a summary dashboard.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from mutagen import __version__
from mutagen.config.container import Container
from mutagen.config.loader import load_config
from mutagen.config.logging import configure_logging, get_logger
from mutagen.core.exceptions import MutagenError
from mutagen.core.models.run import RunResult, RunStatus

_logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="mutagen",
        description="Production-grade mutation testing for Python.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-c", "--config", metavar="PATH",
        help="Path to a Mutagen TOML configuration file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Execute a mutation-testing run.")
    run.add_argument(
        "repo",
        help="Repository to test: a local path or a git URL.",
    )
    run.add_argument(
        "--threshold", type=float, default=None,
        help="Override the minimum acceptable mutation score (0-1).",
    )
    run.add_argument(
        "--run-id", default=None,
        help="Run identifier; reuse to resume an interrupted run.",
    )
    run.add_argument(
        "--no-progress", action="store_true",
        help="Disable the live progress UI (force plain output).",
    )

    report = subparsers.add_parser(
        "report", help="Re-render the most recent run's report."
    )
    report.add_argument(
        "--run-id", default=None,
        help="Run id to report; defaults to the most recent.",
    )

    return parser


async def run_cli(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the selected command.

    Returns:
        A process exit code: ``0`` on success, ``1`` on a handled failure,
        ``2`` when the mutation-score threshold was not met.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {}
    if getattr(args, "threshold", None) is not None:
        overrides["score_threshold"] = args.threshold

    try:
        config = load_config(
            config_path=Path(args.config) if args.config else None,
            overrides=overrides,
        )
    except MutagenError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    configure_logging(config.logging)
    container = Container(config)

    if args.command == "run":
        return await _cmd_run(container, args)
    if args.command == "report":
        return await _cmd_report(container, args)
    parser.error(f"Unknown command: {args.command}")
    return 1  # pragma: no cover - argparse exits first


async def _cmd_run(container: Container, args: argparse.Namespace) -> int:
    """Execute ``mutagen run <repo>``."""
    from mutagen.cli.progress_ui import ProgressUI

    run_id = args.run_id or uuid.uuid4().hex[:12]
    orchestrator = container.provide_orchestrator()

    enabled = False if args.no_progress else None
    try:
        with ProgressUI(enabled=enabled) as ui:
            orchestrator.progress = ui.listener
            result = await orchestrator.execute(args.repo, run_id)
    except MutagenError as exc:
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1

    await _render_dashboard(container, result)
    threshold = container.config.score_threshold
    report = container.provide_reporting_service().summarize(result)
    if threshold > 0 and report.mutation_score < threshold:
        print(
            f"Mutation score {report.mutation_score:.0%} is below the "
            f"threshold {threshold:.0%}.",
            file=sys.stderr,
        )
        return 2
    return 0


async def _cmd_report(container: Container, args: argparse.Namespace) -> int:
    """Re-render a stored run's report."""
    store = container.provide_store()
    run_id = args.run_id
    if run_id is None:
        runs = await store.list_runs(limit=1)
        if not runs:
            print("No runs found to report.", file=sys.stderr)
            return 1
        run_id = runs[0]

    result = await store.load_run(run_id)
    if result is None:
        print(f"Run not found: {run_id}", file=sys.stderr)
        return 1

    report = container.provide_reporting_service().summarize(result)
    await container.provide_reporter().report(report)
    await _render_dashboard(container, result)
    return 0


async def _render_dashboard(container: Container, result: RunResult) -> None:
    """Print the final summary dashboard via the terminal reporter."""
    from mutagen.reporting import TerminalReporter

    report = container.provide_reporting_service().summarize(result)
    await TerminalReporter().report(report)
