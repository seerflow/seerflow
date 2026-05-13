"""CLI handler for ``seerflow export`` (S-076, FR-045).

Streams events or alerts to stdout (or a file) as NDJSON or RFC-4180 CSV.

Design points:
- NDJSON (newline-delimited JSON), not a JSON array — keeps memory O(1) for
  arbitrarily large exports and plays well with ``jq``, ``fluent-bit``, S3
  PutObject chunked transfer.
- Pages of ``_EXPORT_PAGE_SIZE`` rows pulled from the storage layer. The
  storage ``EventQuery.limit`` upper bound (1000) constrains the page size.
- Carriage-return progress messages on stderr only when stderr is a TTY.
  In CI / piped contexts, the progress line is suppressed and a final
  count is printed once on its own line.
- No third-party dependencies (no ``rich``, no ``tqdm``). Stdlib carries
  every primitive we need.
"""
# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import csv
import logging
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

import msgspec.json

from seerflow.config import load_config
from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.query import format_timestamp, parse_duration
from seerflow.storage import connect_storage

if TYPE_CHECKING:
    import argparse
    from collections.abc import AsyncIterator

    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.storage.factory import StorageBackend


_log = logging.getLogger("seerflow")

_EXPORT_PAGE_SIZE = 1000
"""Page size for storage queries. Exposed at module level so tests can flex it."""

_DEFAULT_SINCE = "24h"
"""Default time window when ``--since`` is omitted."""

_DEFAULT_LIMIT = 100_000
"""Default upper bound on total exported rows."""

_PROGRESS_EVERY = _EXPORT_PAGE_SIZE
"""Emit a progress line every N rows."""

_EVENT_CSV_COLUMNS = (
    "event_id",
    "timestamp_ns",
    "severity",
    "source_type",
    "template_id",
    "entity_refs",
    "message",
)

_ALERT_CSV_COLUMNS = (
    "alert_id",
    "timestamp_ns",
    "severity",
    "type",
    "score",
    "rule",
    "description",
    "entity_uuid",
    "entity_type",
    "entity_value",
    "tactics",
    "techniques",
    "dedup_count",
)


def _is_tty() -> bool:
    """Whether stderr is attached to a TTY. Wrapped for test injection."""
    return sys.stderr.isatty()


async def _connect_storage_from_args(args: argparse.Namespace) -> StorageBackend:
    """Resolve config and connect to storage. Wrapped for test injection."""
    config = load_config(args.config)
    return await connect_storage(config.storage)


def _validate_args(args: argparse.Namespace) -> tuple[TimeRange | None, str]:
    """Validate filter args, returning ``(time_range, error_msg)``.

    Returns a (time_range, "") tuple on success, ``(None, msg)`` on failure.
    """
    since = args.since or _DEFAULT_SINCE
    try:
        duration_ns = parse_duration(since)
    except ValueError as exc:
        return None, str(exc)

    severity = getattr(args, "severity", None)
    if severity is not None and not (0 <= severity <= 6):
        return None, f"--severity must be between 0 and 6, got {severity}"

    now_ns = time.time_ns()
    return TimeRange(start_ns=now_ns - duration_ns, end_ns=now_ns), ""


def _open_output(path_str: str | None) -> tuple[TextIO, bool]:
    """Open the output stream. Returns ``(stream, should_close)``.

    Stdout is never closed (the second tuple entry is ``False``); a file
    target is closed by the caller.
    """
    if path_str is None or path_str == "":
        return sys.stdout, False
    path = Path(path_str).expanduser()
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        msg = f"output directory does not exist: {parent}"
        raise FileNotFoundError(msg)
    handle = path.open("w", encoding="utf-8", newline="")
    return handle, True


def _report_progress(count: int, label: str) -> None:
    """Emit a one-line progress update to stderr (TTY-only)."""
    if _is_tty():
        sys.stderr.write(f"\rseerflow export: {count:,} {label}…")
        sys.stderr.flush()


def _finalise_progress(count: int, label: str) -> None:
    """Print the final count on its own line (always, TTY or not)."""
    if _is_tty():
        sys.stderr.write("\n")
        sys.stderr.flush()
    print(f"seerflow export: {count:,} {label} total", file=sys.stderr)


def _event_to_json_dict(event: SeerflowEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "timestamp_ns": event.timestamp_ns,
        "timestamp": format_timestamp(event.timestamp_ns),
        "severity": event.severity_id.name,
        "source_type": event.source_type,
        "template_id": event.template_id,
        "entity_refs": list(event.entity_refs),
        "message": event.message,
    }


def _event_to_csv_row(event: SeerflowEvent) -> list[str]:
    return [
        str(event.event_id),
        str(event.timestamp_ns),
        event.severity_id.name,
        event.source_type,
        str(event.template_id),
        ";".join(event.entity_refs),
        event.message,
    ]


def _alert_to_json_dict(alert: Alert) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "timestamp_ns": alert.timestamp_ns,
        "timestamp": format_timestamp(alert.timestamp_ns),
        "severity": alert.severity_id.name,
        "type": alert.alert_type,
        "score": round(alert.risk_score, 3),
        "rule": alert.rule_name,
        "description": alert.description,
        "entity_uuid": alert.entity_uuid,
        "entity_type": alert.entity_type,
        "entity_value": alert.entity_value,
        "tactics": list(alert.mitre_tactics),
        "techniques": list(alert.mitre_techniques),
        "dedup_count": alert.dedup_count,
    }


def _alert_to_csv_row(alert: Alert) -> list[str]:
    return [
        alert.alert_id,
        str(alert.timestamp_ns),
        alert.severity_id.name,
        alert.alert_type,
        f"{alert.risk_score:.3f}",
        alert.rule_name,
        alert.description,
        alert.entity_uuid,
        alert.entity_type,
        alert.entity_value,
        ";".join(alert.mitre_tactics),
        ";".join(alert.mitre_techniques),
        str(alert.dedup_count),
    ]


async def _iter_events(
    storage: StorageBackend,
    time_range: TimeRange,
    *,
    source_type: str | None,
    severity_min: int | None,
    total_cap: int,
) -> AsyncIterator[SeerflowEvent]:
    """Page through stored events, respecting ``total_cap``."""
    emitted = 0
    page = 1
    while emitted < total_cap:
        page_limit = min(_EXPORT_PAGE_SIZE, total_cap - emitted)
        query = EventQuery(
            time_range=time_range,
            source_type=source_type,
            severity_min=severity_min,
            page=page,
            limit=page_limit,
        )
        result = await storage.query_events(query)
        if not result.items:
            return
        for event in result.items:
            yield event
            emitted += 1
            if emitted >= total_cap:
                return
        if not result.has_next:
            return
        page += 1


async def _iter_alerts(
    storage: StorageBackend,
    time_range: TimeRange,
    *,
    alert_type: Any,
    severity_min: int | None,
    total_cap: int,
) -> AsyncIterator[Alert]:
    """Page through stored alerts, respecting ``total_cap``."""
    emitted = 0
    page = 1
    while emitted < total_cap:
        page_limit = min(_EXPORT_PAGE_SIZE, total_cap - emitted)
        query = AlertQuery(
            time_range=time_range,
            alert_type=alert_type,
            severity_min=severity_min,
            page=page,
            limit=page_limit,
        )
        result = await storage.query_alerts(query)
        if not result.items:
            return
        for alert in result.items:
            yield alert
            emitted += 1
            if emitted >= total_cap:
                return
        if not result.has_next:
            return
        page += 1


async def _export_events_json(
    stream: TextIO,
    iterator: AsyncIterator[SeerflowEvent],
) -> int:
    """Write events as NDJSON. Returns the number of records emitted."""
    count = 0
    async for event in iterator:
        line = msgspec.json.encode(_event_to_json_dict(event)).decode("utf-8")
        stream.write(line)
        stream.write("\n")
        count += 1
        if count % _PROGRESS_EVERY == 0:
            _report_progress(count, "events")
    return count


async def _export_events_csv(
    stream: TextIO,
    iterator: AsyncIterator[SeerflowEvent],
) -> int:
    """Write events as RFC-4180 CSV. Returns the number of records emitted."""
    writer = csv.writer(stream)
    writer.writerow(_EVENT_CSV_COLUMNS)
    count = 0
    async for event in iterator:
        writer.writerow(_event_to_csv_row(event))
        count += 1
        if count % _PROGRESS_EVERY == 0:
            _report_progress(count, "events")
    return count


async def _export_alerts_json(
    stream: TextIO,
    iterator: AsyncIterator[Alert],
) -> int:
    """Write alerts as NDJSON. Returns the number of records emitted."""
    count = 0
    async for alert in iterator:
        line = msgspec.json.encode(_alert_to_json_dict(alert)).decode("utf-8")
        stream.write(line)
        stream.write("\n")
        count += 1
        if count % _PROGRESS_EVERY == 0:
            _report_progress(count, "alerts")
    return count


async def _export_alerts_csv(
    stream: TextIO,
    iterator: AsyncIterator[Alert],
) -> int:
    """Write alerts as RFC-4180 CSV. Returns the number of records emitted."""
    writer = csv.writer(stream)
    writer.writerow(_ALERT_CSV_COLUMNS)
    count = 0
    async for alert in iterator:
        writer.writerow(_alert_to_csv_row(alert))
        count += 1
        if count % _PROGRESS_EVERY == 0:
            _report_progress(count, "alerts")
    return count


async def run_export(args: argparse.Namespace) -> int:
    """Run the ``seerflow export`` command. Returns a process exit code.

    Exit codes:
        0 — success
        1 — unexpected runtime error
        2 — input validation error (bad duration, severity, output path,
            unknown export_type)
    """
    export_type = getattr(args, "export_type", None)
    if export_type not in {"events", "alerts"}:
        print(
            f"Error: unknown export type {export_type!r}. Expected 'events' or 'alerts'.",
            file=sys.stderr,
        )
        return 2

    time_range, err = _validate_args(args)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    assert time_range is not None  # narrowing for mypy

    try:
        stream, should_close = _open_output(args.output)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error opening output: {exc}", file=sys.stderr)
        return 2

    storage = await _connect_storage_from_args(args)
    total_cap = args.limit if args.limit is not None else _DEFAULT_LIMIT

    async with AsyncExitStack() as stack:
        stack.push_async_callback(storage.close)
        if should_close:
            stack.callback(stream.close)

        try:
            if export_type == "events":
                events_iter = _iter_events(
                    storage,
                    time_range,
                    source_type=args.source,
                    severity_min=args.severity,
                    total_cap=total_cap,
                )
                if args.format == "csv":
                    count = await _export_events_csv(stream, events_iter)
                else:
                    count = await _export_events_json(stream, events_iter)
                label = "events"
            else:
                alerts_iter = _iter_alerts(
                    storage,
                    time_range,
                    alert_type=args.type,
                    severity_min=args.severity,
                    total_cap=total_cap,
                )
                if args.format == "csv":
                    count = await _export_alerts_csv(stream, alerts_iter)
                else:
                    count = await _export_alerts_json(stream, alerts_iter)
                label = "alerts"
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            _log.exception("export failed")
            return 1

        stream.flush()
        _finalise_progress(count, label)
        return 0

    return 0  # pragma: no cover — AsyncExitStack always exits via return above


__all__ = ["run_export"]
