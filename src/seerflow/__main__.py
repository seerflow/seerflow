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


def _run_async_int(coro: Coroutine[Any, Any, int]) -> int:
    """Run a coroutine returning an exit code, with uvloop fallback."""
    try:
        import uvloop

        return uvloop.run(coro)
    except ImportError:
        return asyncio.run(coro)


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        if args.command == "start":
            from seerflow.pipeline.run import _run

            _run_async(_run(args.config))
        elif args.command == "status":
            from seerflow.status_cmd import run_status

            sys.exit(_run_async_int(run_status(args)))
        elif args.command == "tail":
            from seerflow.pipeline.run import _run_with_config
            from seerflow.pipeline.tail import _build_tail_config

            tail_config = _build_tail_config(args.paths, config_path=args.config)
            _run_async(_run_with_config(tail_config))
        elif args.command == "query":
            from seerflow.query import run_query

            _run_async(run_query(args))
        elif args.command == "import":
            from seerflow.config import load_config
            from seerflow.import_cmd import run_import

            db_path = args.db
            if db_path is None:
                from pathlib import Path

                cfg = load_config(args.config)
                db_path = cfg.storage.sqlite_path or str(
                    Path(cfg.storage.data_dir) / "seerflow.db"
                )

            async def _do_import() -> None:
                await run_import(paths=args.paths, db_path=db_path)

            _run_async(_do_import())
        elif args.command == "feedback":
            from seerflow.feedback_cmd import run_feedback

            _run_async(run_feedback(args))
        elif args.command == "hunt":
            from seerflow.hunt_cmd import run_hunt

            sys.exit(_run_async_int(run_hunt(args)))
        elif args.command == "export":
            from seerflow.export_cmd import run_export

            sys.exit(_run_async_int(run_export(args)))
        elif args.command == "templates":
            from seerflow.templates_cmd import run_templates

            sys.exit(_run_async_int(run_templates(args)))
        elif args.command == "rules":
            from seerflow.rules_cmd import run_rules_list

            sys.exit(run_rules_list(args))
        elif args.command == "graph":
            from seerflow.graph_migrate_cmd import run_graph_migrate

            sys.exit(_run_async_int(run_graph_migrate(args)))
        else:
            raise AssertionError(f"Unhandled command: {args.command!r}")
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
