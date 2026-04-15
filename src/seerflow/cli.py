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
    al.add_argument(
        "--tactic", type=str.lower, default=None, help="Filter by ATT&CK tactic (e.g., discovery)"
    )
    al.add_argument(
        "--technique",
        type=str.lower,
        default=None,
        help="Filter by ATT&CK technique (e.g., t1033)",
    )

    # --- query templates ---
    tpl = query_sub.add_parser("templates", help="Query Drain3 templates")
    tpl.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    tpl.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    # --- query timeline ---
    tl = query_sub.add_parser("timeline", help="Entity timeline by UUID")
    tl.add_argument("entity_uuid", help="Entity UUID5 string")
    tl.add_argument("--last", type=str, default=None, help="Time window (e.g., 1h, 30m, 7d)")
    tl.add_argument("--source", type=str, default=None, help="Filter by source type")
    tl.add_argument("--severity", type=int, default=None, help="Minimum severity (0-6)")
    tl.add_argument("--limit", type=int, default=1000, help="Max results (default: 1000)")
    tl.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    # --- query health ---
    health = query_sub.add_parser("health", help="Detection ensemble health stats")
    health.add_argument("--json", action="store_true", default=False, help="Output as JSON")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
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
    subparsers.required = True

    subparsers.add_parser("start", help="Start the Seerflow pipeline")

    tail_parser = subparsers.add_parser("tail", help="Monitor log files (no config needed)")
    tail_parser.add_argument("paths", nargs="+", help="File paths or glob patterns")

    import_parser = subparsers.add_parser("import", help="Import log files into Seerflow")
    import_parser.add_argument("paths", nargs="+", help="Log file paths or glob patterns")
    import_parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Database path (default: from config)",
    )

    _add_query_subparsers(subparsers)

    feedback_parser = subparsers.add_parser("feedback", help="Mark alert as TP/FP")
    feedback_parser.add_argument("alert_id", help="Alert ID")
    feedback_parser.add_argument("type", choices=["tp", "fp"], help="Feedback type")
    feedback_parser.add_argument("--note", default="", help="Optional note")

    rules_parser = subparsers.add_parser("rules", help="Inspect loaded Sigma rules")
    rules_sub = rules_parser.add_subparsers(dest="rules_cmd")
    rules_sub.required = True

    rules_list = rules_sub.add_parser("list", help="List all loaded Sigma rules")
    rules_list.add_argument(
        "--technique",
        type=str,
        default=None,
        help="Filter by ATT&CK technique (e.g., T1053 — prefix match includes sub-techniques)",
    )
    rules_list.add_argument(
        "--tactic",
        type=str,
        default=None,
        help="Filter by ATT&CK tactic name (e.g., persistence) or ID (e.g., TA0003)",
    )
    rules_list.add_argument(
        "--format",
        type=str,
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    return build_parser().parse_args(argv)


__all__ = ["build_parser", "parse_args"]
