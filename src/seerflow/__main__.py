"""Entry point for ``python -m seerflow``."""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from seerflow.config import SeerflowConfig

from seerflow.cli import parse_args


def _apply_console_overrides(
    cfg: SeerflowConfig,
    alerts_to: str | None,
    alerts_format: Literal["human", "json"] | None,
) -> SeerflowConfig:
    """Apply ``start --alerts-to/--alerts-format`` over the loaded config.

    S-312/FR-071: ``--alerts-to`` is shared with the S-313 file sink, so only
    the ``"stdout"``/``"stderr"`` values select the console stream here (any
    other value is a file path handled by :func:`_apply_alerts_to`).
    ``--alerts-format`` selects the console format. Both win over
    ``seerflow.yaml``. Config is frozen, so a new instance is returned via
    ``dataclasses.replace`` (no mutation).
    """
    console_stream: Literal["stdout", "stderr"] | None = None
    if alerts_to == "stdout":
        console_stream = "stdout"
    elif alerts_to == "stderr":
        console_stream = "stderr"
    if console_stream is None and alerts_format is None:
        return cfg
    alerting = cfg.alerting
    if console_stream is not None:
        alerting = dataclasses.replace(
            alerting, console_enabled=True, console_stream=console_stream
        )
    if alerts_format is not None:
        alerting = dataclasses.replace(alerting, console_format=alerts_format)
    return dataclasses.replace(cfg, alerting=alerting)


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


def _apply_alerts_to(config: SeerflowConfig, alerts_to: str | None) -> SeerflowConfig:
    """Return ``config`` with a CLI ``--alerts-to`` file target applied (S-313).

    No-op (identity) when ``alerts_to`` is ``None`` or one of the console
    stream sentinels ``"stdout"``/``"stderr"`` (those are owned by
    :func:`_apply_console_overrides`, since S-312 and S-313 share the
    ``--alerts-to`` flag). Config is frozen, so the override is a
    ``dataclasses.replace`` copy (no mutation). Path validity is enforced by
    ``_validate_writable_target`` via the assembly path / config load — an
    invalid path fails fast at startup.
    """
    if alerts_to is None or alerts_to in ("stdout", "stderr"):
        return config
    import dataclasses

    alerting = dataclasses.replace(config.alerting, file_enabled=True, file_path=alerts_to)
    return dataclasses.replace(config, alerting=alerting)


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    # S-089: imported here (not at module top) so ``--help`` / arg parsing
    # never pull in the heavy ``seerflow.config`` import chain (and its
    # third-party deps). This preserves the existing lazy-import invariant
    # of this dispatcher — config is only loaded once a command runs.
    from seerflow.config import ConfigError

    try:
        if args.command == "start":
            if getattr(args, "tui", False):
                # S-079: --tui launches the Textual headless dashboard
                # alongside the pipeline. Falls back to the plain pipeline
                # path on graceful textual absence (handled inside the
                # launcher, no branch here).
                from seerflow.config import load_config
                from seerflow.tui import launch_tui_with_pipeline

                _run_async(launch_tui_with_pipeline(load_config(args.config)))
            else:
                from seerflow.config import load_config
                from seerflow.pipeline.run import _run_with_config

                _alerts_to = getattr(args, "alerts_to", None)
                _cfg = _apply_console_overrides(
                    load_config(args.config),
                    _alerts_to,
                    getattr(args, "alerts_format", None),
                )
                _cfg = _apply_alerts_to(_cfg, _alerts_to)
                _run_async(_run_with_config(_cfg))
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
        elif args.command == "analyze":
            from seerflow.analyze_cmd import run_analyze

            sys.exit(_run_async_int(run_analyze(args)))
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
        elif args.command == "validate":
            from seerflow.validate_cmd import run_validate

            sys.exit(run_validate(args))
        elif args.command == "benchmark":
            from seerflow.benchmark_cmd import run_benchmark_cmd

            sys.exit(run_benchmark_cmd(args))
        elif args.command == "lanl-report":
            from seerflow.lanl.report_cmd import run_lanl_report

            sys.exit(run_lanl_report(args))
        else:
            raise AssertionError(f"Unhandled command: {args.command!r}")
    except KeyboardInterrupt:
        sys.exit(0)
    except ConfigError as exc:
        # S-089: a hand-edited seerflow.yaml is the most likely first-run
        # failure. Translate the (already-actionable) ConfigError message
        # into a clean stderr line + exit 1 instead of a raw traceback so a
        # new evaluator can fix their config within the NFR-005 window.
        print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
