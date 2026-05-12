"""CLI handler for ``seerflow hunt`` command (S-072, FR-057).

Loads the seerflow config, builds the LLM backend + ``NaturalLanguageHuntService``,
and dispatches the natural-language query. Prints results as a table by default
or as a JSON envelope when ``--json`` is set.

When the LLM backend is unavailable (disabled / degraded / dep missing) the
command falls back gracefully — it prints a helpful pointer at the structured
``seerflow query events`` syntax and exits 0 (degraded, not crashed).
"""
# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import msgspec.json

from seerflow.cli_format import format_table
from seerflow.config import load_config
from seerflow.llm import build_llm_backend
from seerflow.llm.hunt.cache import HuntCache
from seerflow.llm.hunt.service import NaturalLanguageHuntService
from seerflow.query import format_timestamp
from seerflow.storage import connect_storage

if TYPE_CHECKING:
    import argparse

    from seerflow.llm.hunt.result import HuntResult
    from seerflow.storage.factory import StorageBackend


_log = logging.getLogger("seerflow")


async def _build_service_and_storage(
    args: argparse.Namespace,
) -> tuple[NaturalLanguageHuntService | None, StorageBackend]:
    """Construct the hunt service + storage backend from CLI args.

    Returns ``(service, storage)``. ``service`` is ``None`` when the LLM
    backend is unavailable; the caller prints a fallback message and exits 0.
    The storage backend is always returned so the caller can close it.
    """
    config = load_config(args.config)
    storage = await connect_storage(config.storage)
    llm_backend = build_llm_backend(config.llm)
    if llm_backend is None:
        return None, storage
    cache = HuntCache(
        max_entries=config.llm.hunt_cache_size,
        ttl_seconds=config.llm.hunt_cache_ttl_s,
    )
    service = NaturalLanguageHuntService(
        backend=llm_backend,
        cache=cache,
        cfg=config.llm,
        log_store=storage,
    )
    return service, storage


def _print_fallback() -> None:
    print(
        "LLM backend not available — natural language hunting is disabled.\n"
        "Use the structured query syntax instead:\n"
        "  seerflow query events --help",
        file=sys.stderr,
    )


def _print_json(result: HuntResult) -> None:
    payload = {
        "query": result.query,
        "filters": result.filters,
        "events": [
            {
                "event_id": str(e.event_id),
                "timestamp": format_timestamp(e.timestamp_ns),
                "severity": e.severity_id.name,
                "source_type": e.source_type,
                "template_id": e.template_id,
                "message": e.message,
            }
            for e in result.events
        ],
        "total": result.total,
        "model": result.model,
        "cached": result.cached,
        "truncated": result.truncated,
        "latency_ms": result.latency_ms,
    }
    encoded = msgspec.json.encode(payload)
    sys.stdout.buffer.write(encoded)
    print()


def _print_table(result: HuntResult) -> None:
    print(f"Query: {result.query}")
    print(f"Filters: {result.filters}")
    print(f"Model: {result.model}  cached: {result.cached}  latency_ms: {result.latency_ms:.1f}")
    if not result.events:
        print("No events found.")
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
        for e in result.events
    ]
    print(format_table(headers, rows), end="")
    print(f"\n{result.total} event(s) total, showing {len(result.events)}")


async def run_hunt(args: argparse.Namespace) -> int:
    """Run the ``seerflow hunt`` command. Returns a process exit code."""
    service, storage = await _build_service_and_storage(args)
    try:
        if service is None:
            _print_fallback()
            return 0
        try:
            result = await service.hunt(args.query)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            _log.exception("hunt failed")
            return 1

        if args.json:
            _print_json(result)
        else:
            _print_table(result)
        return 0
    finally:
        await storage.close()
