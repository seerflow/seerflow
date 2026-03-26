"""Query execution and formatting for the seerflow CLI.

Provides ``seerflow query events|alerts|templates`` subcommands.
"""
# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import re
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import msgspec.json

if TYPE_CHECKING:
    import argparse

    from seerflow.storage.sqlite import SqliteBackend


_DURATION_RE = re.compile(r"^(\d+)([mhd])$")
_UNIT_TO_NS: dict[str, int] = {
    "m": 60 * 1_000_000_000,
    "h": 3_600_000_000_000,
    "d": 24 * 3_600_000_000_000,
}


def parse_duration(s: str) -> int:
    """Parse a human-readable duration string to nanoseconds.

    Supported formats: ``30m`` (minutes), ``1h`` (hours), ``7d`` (days).
    Raises ``ValueError`` on invalid input.
    """
    match = _DURATION_RE.match(s)
    if not match:
        msg = f"Invalid duration '{s}'. Use format like '1h', '30m', '7d'"
        raise ValueError(msg)
    value = int(match.group(1))
    if value <= 0:
        msg = f"Invalid duration '{s}'. Value must be positive"
        raise ValueError(msg)
    return value * _UNIT_TO_NS[match.group(2)]


def format_timestamp(ns: int) -> str:
    """Convert nanosecond timestamp to ``YYYY-MM-DD HH:MM:SS`` local time."""
    dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC)
    local_dt = dt.astimezone()
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format headers and rows into an auto-sized text table.

    Computes maximum width per column, pads with spaces, and adds
    a separator line of dashes below the header row.
    """
    if not headers:
        return ""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    lines = [fmt.format(*headers)]
    lines.append("  ".join("-" * w for w in col_widths))
    for row in rows:
        padded = row + [""] * (len(headers) - len(row))
        lines.append(fmt.format(*padded[: len(headers)]))
    return "\n".join(lines) + "\n"


async def run_query_events(storage: SqliteBackend, args: argparse.Namespace) -> None:
    """Execute event query and print results."""
    from seerflow.models.query import EventQuery, TimeRange

    time_range = None
    if args.last:
        try:
            now_ns = time.time_ns()
            duration_ns = parse_duration(args.last)
            time_range = TimeRange(start_ns=now_ns - duration_ns, end_ns=now_ns)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return

    query = EventQuery(
        time_range=time_range,
        template_id=args.template,
        source_type=args.source,
        severity_min=args.severity,
        limit=args.limit,
    )
    result = await storage.query_events(query)

    if not result.items:
        print("No events found.")
        return

    if args.json:
        encoded = msgspec.json.encode(
            [
                {
                    "event_id": str(e.event_id),
                    "timestamp": format_timestamp(e.timestamp_ns),
                    "severity": e.severity_id.name,
                    "source_type": e.source_type,
                    "template_id": e.template_id,
                    "message": e.message,
                }
                for e in result.items
            ]
        )
        sys.stdout.buffer.write(encoded)
        print()
        return

    headers = ["TIMESTAMP", "SEVERITY", "SOURCE", "TID", "MESSAGE"]
    rows = [
        [
            format_timestamp(e.timestamp_ns),
            e.severity_id.name,
            e.source_type,
            str(e.template_id),
            e.message[:60],
        ]
        for e in result.items
    ]
    print(format_table(headers, rows), end="")
    print(f"\n{result.total} event(s) total, showing {len(result.items)}")


async def run_query_alerts(storage: SqliteBackend, args: argparse.Namespace) -> None:
    """Execute alert query and print results."""
    from seerflow.models.query import AlertQuery, TimeRange

    time_range = None
    if args.last:
        try:
            now_ns = time.time_ns()
            duration_ns = parse_duration(args.last)
            time_range = TimeRange(start_ns=now_ns - duration_ns, end_ns=now_ns)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return

    query = AlertQuery(
        time_range=time_range,
        alert_type=args.type,
        severity_min=args.severity,
        limit=args.limit,
    )
    result = await storage.query_alerts(query)

    if not result.items:
        print("No alerts found.")
        return

    if args.json:
        encoded = msgspec.json.encode(
            [
                {
                    "alert_id": a.alert_id,
                    "timestamp": format_timestamp(a.timestamp_ns),
                    "type": a.alert_type,
                    "severity": a.severity_id.name,
                    "score": round(a.risk_score, 3),
                    "rule": a.rule_name,
                    "dedup_count": a.dedup_count,
                    "description": a.description,
                }
                for a in result.items
            ]
        )
        sys.stdout.buffer.write(encoded)
        print()
        return

    headers = ["TIMESTAMP", "TYPE", "SEVERITY", "SCORE", "RULE", "DEDUP", "DESCRIPTION"]
    rows = [
        [
            format_timestamp(a.timestamp_ns),
            a.alert_type,
            a.severity_id.name,
            f"{a.risk_score:.3f}",
            a.rule_name,
            str(a.dedup_count),
            a.description[:50],
        ]
        for a in result.items
    ]
    print(format_table(headers, rows), end="")
    print(f"\n{result.total} alert(s) total, showing {len(result.items)}")


async def run_query_templates(storage: SqliteBackend, args: argparse.Namespace) -> None:
    """Execute template query and print results."""
    templates = await storage.get_templates(limit=args.limit)

    if not templates:
        print("No templates found.")
        return

    if args.json:
        encoded = msgspec.json.encode(
            [
                {
                    "template_id": t.template_id,
                    "event_count": t.event_count,
                    "first_seen": format_timestamp(t.first_seen_ns),
                    "last_seen": format_timestamp(t.last_seen_ns),
                    "template": t.template_str,
                }
                for t in templates
            ]
        )
        sys.stdout.buffer.write(encoded)
        print()
        return

    headers = ["TID", "COUNT", "FIRST SEEN", "LAST SEEN", "TEMPLATE"]
    rows = [
        [
            str(t.template_id),
            str(t.event_count),
            format_timestamp(t.first_seen_ns),
            format_timestamp(t.last_seen_ns),
            t.template_str[:80],
        ]
        for t in templates
    ]
    print(format_table(headers, rows), end="")
    print(f"\n{len(templates)} template(s)")


async def run_query(args: argparse.Namespace) -> None:
    """Top-level query dispatcher — load config, connect storage, route."""
    from seerflow.config import load_config
    from seerflow.storage.sqlite import SqliteBackend

    config = load_config(args.config)
    storage = await SqliteBackend.connect(config.storage)
    try:
        if args.query_type == "events":
            await run_query_events(storage, args)
        elif args.query_type == "alerts":
            await run_query_alerts(storage, args)
        elif args.query_type == "templates":
            await run_query_templates(storage, args)
        else:
            msg = f"Unknown query_type: {args.query_type!r}"
            raise ValueError(msg)
    finally:
        await storage.close()
