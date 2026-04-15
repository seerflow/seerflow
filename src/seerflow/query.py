"""Query execution and formatting for the seerflow CLI.

Provides ``seerflow query events|alerts|templates`` subcommands.
"""
# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import dataclasses
import re
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import msgspec.json
import yaml

from seerflow.cli_format import format_table
from seerflow.sigma.attack import format_tactic, format_technique

if TYPE_CHECKING:
    import argparse

    from seerflow.storage.sqlite import SqliteBackend


_DURATION_RE = re.compile(r"^(\d+)([mhd])$")
_UNIT_TO_NS: dict[str, int] = {
    "m": 60 * 1_000_000_000,
    "h": 3_600_000_000_000,
    "d": 24 * 3_600_000_000_000,
}
_VALID_ALERT_TYPES = {"ml", "sigma", "correlation", "ueba", "ioc"}


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


async def run_query_events(storage: SqliteBackend, args: argparse.Namespace) -> None:
    """Execute event query and print results."""
    from seerflow.models.query import EventQuery, TimeRange

    if args.severity is not None and not (0 <= args.severity <= 6):
        print(
            f"Error: --severity must be between 0 and 6, got {args.severity}",
            file=sys.stderr,
        )
        return

    time_range = None
    if args.last:
        try:
            now_ns = time.time_ns()
            duration_ns = parse_duration(args.last)
            time_range = TimeRange(start_ns=now_ns - duration_ns, end_ns=now_ns)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return

    try:
        query = EventQuery(
            time_range=time_range,
            template_id=args.template,
            source_type=args.source,
            severity_min=args.severity,
            limit=args.limit,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return
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

    if args.type is not None and args.type not in _VALID_ALERT_TYPES:
        print(
            f"Error: unknown alert type '{args.type}'. "
            f"Valid: {', '.join(sorted(_VALID_ALERT_TYPES))}",
            file=sys.stderr,
        )
        return

    if args.tactic is not None:
        from seerflow.sigma.attack import TACTICS, is_valid_tactic

        if not is_valid_tactic(args.tactic):
            print(
                f"Error: unknown tactic '{args.tactic}'. Valid: {', '.join(sorted(TACTICS))}",
                file=sys.stderr,
            )
            return

    if args.severity is not None and not (0 <= args.severity <= 6):
        print(
            f"Error: --severity must be between 0 and 6, got {args.severity}",
            file=sys.stderr,
        )
        return

    time_range = None
    if args.last:
        try:
            now_ns = time.time_ns()
            duration_ns = parse_duration(args.last)
            time_range = TimeRange(start_ns=now_ns - duration_ns, end_ns=now_ns)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return

    try:
        query = AlertQuery(
            time_range=time_range,
            alert_type=args.type,
            severity_min=args.severity,
            limit=args.limit,
            tactic=args.tactic,
            technique=args.technique,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return
    result = await storage.query_alerts(query)

    # Post-decode filtering for tactic/technique (stored in msgpack BLOB,
    # not SQL-queryable). Applied over the fetched page only — results may
    # be fewer than limit when many non-matching alerts exist.
    if query.tactic or query.technique:
        filtered = []
        for a in result.items:
            if query.tactic and query.tactic not in a.mitre_tactics:
                continue
            if query.technique and query.technique not in a.mitre_techniques:
                continue
            filtered.append(a)
        result = dataclasses.replace(result, items=tuple(filtered), total=len(filtered))

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
                    "tactics": [format_tactic(t) for t in a.mitre_tactics],
                    "techniques": [format_technique(t) for t in a.mitre_techniques],
                    "dedup_count": a.dedup_count,
                    "description": a.description,
                }
                for a in result.items
            ]
        )
        sys.stdout.buffer.write(encoded)
        print()
        return

    headers = [
        "TIMESTAMP",
        "TYPE",
        "SEVERITY",
        "SCORE",
        "RULE",
        "TACTICS",
        "TECHNIQUES",
        "DEDUP",
        "DESCRIPTION",
    ]
    rows = [
        [
            format_timestamp(a.timestamp_ns),
            a.alert_type,
            a.severity_id.name,
            f"{a.risk_score:.3f}",
            a.rule_name,
            ", ".join(format_tactic(t) for t in a.mitre_tactics) or "-",
            ", ".join(format_technique(t) for t in a.mitre_techniques) or "-",
            str(a.dedup_count),
            a.description[:40],
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


_DEFAULT_TIMELINE_WINDOW_NS = 24 * 3_600_000_000_000  # 24 hours


async def run_query_timeline(storage: SqliteBackend, args: argparse.Namespace) -> None:
    """Execute entity timeline query and print results."""
    import uuid as _uuid_mod

    from seerflow.models.query import TimeRange

    try:
        _uuid_mod.UUID(args.entity_uuid)
    except ValueError:
        print(
            f"Error: entity_uuid must be a valid UUID, got {args.entity_uuid!r}",
            file=sys.stderr,
        )
        return

    if args.severity is not None and not (0 <= args.severity <= 6):
        print(
            f"Error: --severity must be between 0 and 6, got {args.severity}",
            file=sys.stderr,
        )
        return

    now_ns = time.time_ns()
    if args.last:
        try:
            duration_ns = parse_duration(args.last)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return
    else:
        duration_ns = _DEFAULT_TIMELINE_WINDOW_NS

    time_range = TimeRange(start_ns=now_ns - duration_ns, end_ns=now_ns)

    events = await storage.get_timeline(
        args.entity_uuid,
        time_range,
        source_type=args.source,
        severity_min=args.severity,
        limit=args.limit,
    )

    if not events:
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
                for e in events
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
        for e in events
    ]
    print(format_table(headers, rows), end="")
    print(f"\n{len(events)} event(s)")


def _format_bytes(n: int) -> str:
    """Format byte count as human-readable string."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:,.0f} KB"
    return f"{n / (1024 * 1024):,.1f} MB"


def format_health_table(health: dict[str, Any]) -> str:
    """Format health dict as a human-readable table."""
    lines: list[str] = []
    src = health["source_count"]
    mx = health["max_sources"]
    pct = (src / mx * 100) if mx > 0 else 0.0

    lines.append("Detection Ensemble Health")
    lines.append("=" * 40)
    lines.append(f"Sources:       {src} / {mx}  ({pct:.1f}%)")
    lines.append(f"Evictions:     {health['eviction_count']}  (source)")
    lines.append(
        f"               {health['template_hw_eviction_count']}  (template HW)"
        f"  {health['entity_hw_eviction_count']}  (entity HW)"
    )
    lines.append("")

    mem = health["memory_by_type"]
    rows = [
        ["HST", str(src), _format_bytes(mem["hst"])],
        ["HW (source)", str(src), _format_bytes(mem["hw_source"])],
        ["HW (template)", str(health["template_hw_count"]), _format_bytes(mem["hw_template"])],
        ["HW (entity)", str(health["entity_hw_count"]), _format_bytes(mem["hw_entity"])],
        ["CUSUM", str(src), _format_bytes(mem["cusum"])],
        ["DSPOT", str(src), _format_bytes(mem["dspot"])],
        [
            "Markov",
            str(sum(health.get("markov_entity_counts", {}).values())),
            _format_bytes(mem["markov"]),
        ],
    ]

    lines.append(format_table(["DETECTOR", "COUNT", "MEMORY"], rows))
    lines.append(f"Total: {_format_bytes(health['estimated_memory_bytes'])}")

    markov = health.get("markov_entity_counts", {})
    if markov:
        lines.append("")
        lines.append("Markov Entities by Source")
        lines.append("-" * 30)
        entity_rows = [[s, str(c)] for s, c in sorted(markov.items(), key=lambda x: -x[1])]
        lines.append(format_table(["SOURCE", "ENTITIES"], entity_rows))

    return "\n".join(lines)


async def run_query_health(args: argparse.Namespace) -> None:
    """Execute health query — load ensemble from storage, print stats."""
    from seerflow.config import ConfigError, load_config
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.storage.sqlite import SqliteBackend

    try:
        config = load_config(args.config)
    except (ConfigError, FileNotFoundError, yaml.YAMLError) as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        storage = await SqliteBackend.connect(config.storage)
    except OSError as exc:
        print(f"Error connecting to storage: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        ensemble = DetectionEnsemble(config.detection)
        await ensemble.load_all_state(storage)
        health = ensemble.get_health()
    finally:
        await storage.close()

    if args.json:
        encoded = msgspec.json.encode(health)
        sys.stdout.buffer.write(encoded)
        print()
    else:
        print(format_health_table(health))


async def run_query(args: argparse.Namespace) -> None:
    """Top-level query dispatcher — load config, connect storage, route."""
    # Health manages its own config/storage (needs config.detection for ensemble).
    if args.query_type == "health":
        await run_query_health(args)
        return

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
        elif args.query_type == "timeline":
            await run_query_timeline(storage, args)
        else:
            msg = f"Unknown query_type: {args.query_type!r}"
            raise ValueError(msg)
    finally:
        await storage.close()
