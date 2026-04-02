"""Entry point for ``python -m seerflow``."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

from seerflow.cli import parse_args


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine using uvloop when available, falling back to asyncio."""
    try:
        import uvloop

        uvloop.run(coro)
    except ImportError:
        asyncio.run(coro)


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        if args.command == "start":
            from seerflow.pipeline.run import _run

            _run_async(_run(args.config))
        elif args.command == "tail":
            from seerflow.pipeline.run import _run_with_config
            from seerflow.pipeline.tail import _build_tail_config

            tail_config = _build_tail_config(args.paths, config_path=args.config)
            _run_async(_run_with_config(tail_config))
        elif args.command == "query":
            from seerflow.query import run_query

            _run_async(run_query(args))
        else:
            raise AssertionError(f"Unhandled command: {args.command!r}")
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
