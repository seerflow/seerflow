"""Entry point for ``python -m seerflow``."""

from __future__ import annotations

import asyncio
import sys

from seerflow.cli import parse_args


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        if args.command == "tail":
            from seerflow.pipeline.run import _run_with_config
            from seerflow.pipeline.tail import _build_tail_config

            tail_config = _build_tail_config(args.paths, config_path=args.config)
            asyncio.run(_run_with_config(tail_config))
        elif args.command == "query":
            from seerflow.query import run_query

            asyncio.run(run_query(args))
        else:
            from seerflow.pipeline.run import _run

            asyncio.run(_run(args.config))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
