"""Project entrypoint.

Thin executable shim that delegates to the asynchronous CLI. Keeping the
entrypoint minimal ensures all real wiring happens in the CLI and DI layers.

Run as either ``python -m mutagen.main`` or via the ``mutagen`` console script.
"""

from __future__ import annotations

import asyncio
import sys

from mutagen.cli import run_cli


def main() -> int:
    """Synchronous entrypoint that runs the async CLI to completion.

    Returns:
        The process exit code produced by the CLI.
    """
    return asyncio.run(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
