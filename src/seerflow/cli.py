"""CLI argument parsing for the seerflow command."""

from __future__ import annotations

import argparse

from seerflow import __version__


def _add_query_subparsers(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Add ``seerflow query events|alerts|templates`` subcommands."""
    query_parser = subparsers.add_parser("query", help="Query stored data")
    query_sub = query_parser.add_subparsers(dest="query_type")
    query_sub.required = True

    # --- query events ---
    ev = query_sub.add_parser("events", help="Query stored events")
    ev.add_argument("--last", type=str, default=None, help="Time window (e.g., 1h, 30m, 7d)")
    ev.add_argument("--template", type=int, default=None, help="Filter by template ID")
    ev.add_argument("--source", type=str, default=None, help="Filter by source type")
    ev.add_argument("--severity", type=int, default=None, help="Minimum severity (0-6)")
    ev.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    ev.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    # --- query alerts ---
    al = query_sub.add_parser("alerts", help="Query stored alerts")
    al.add_argument("--last", type=str, default=None, help="Time window (e.g., 1h, 30m, 7d)")
    al.add_argument("--type", type=str, default=None, help="Alert type (ml, sigma, etc.)")
    al.add_argument("--severity", type=int, default=None, help="Minimum severity (0-6)")
    al.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    al.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    # --- query templates ---
    tpl = query_sub.add_parser("templates", help="Query Drain3 templates")
    tpl.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    tpl.add_argument("--json", action="store_true", default=False, help="Output as JSON")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="seerflow",
        description="Streaming log intelligence agent",
    )
    parser.add_argument("--version", action="version", version=f"seerflow {__version__}")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to seerflow.yaml config file",
    )

    subparsers = parser.add_subparsers(dest="command")
    tail_parser = subparsers.add_parser("tail", help="Monitor log files (no config needed)")
    tail_parser.add_argument("paths", nargs="+", help="File paths or glob patterns")

    _add_query_subparsers(subparsers)

    return parser.parse_args(argv)


__all__ = ["parse_args"]
