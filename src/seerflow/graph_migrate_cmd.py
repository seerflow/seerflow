"""CLI handler for ``seerflow graph migrate`` (S-155-F3).

Streams every entity-graph edge from one ``GraphBackend`` to another so
operators can graduate from the default in-process ``igraph`` to a
persistent backend (FalkorDB, PostgreSQL AGE) — or downgrade — without
writing a throwaway migration script.

Design points:

- The handler orchestrates two ``GraphBackend`` instances over the
  existing Protocol surface (``export_edges`` + ``add_edge``). **No new
  Protocol methods.** ``export_edges()`` returns the source-side edge
  list; the handler chunks it by ``--batch-size`` and replays each row
  through ``dest.add_edge``.
- Every backend's ``add_edge`` is a MERGE on ``(src, tgt, rel_type)``
  with ``min(first_seen) / max(last_seen) / event_count`` semantics — so
  the migration is **idempotent** by construction. Re-running the same
  command is a no-op on the destination.
- Default migration is **additive**: the destination's pre-existing
  edges are preserved. ``--wipe-destination`` opt-in clears the
  destination via ``await dest.load([])`` before streaming, enabling a
  strict-equality verification step.
- ``--dry-run`` connects to the **source only**, reports the projected
  edge / vertex counts, and exits 0 without touching the destination.
- Verification post-migration compares ``edge_count`` and
  ``vertex_count`` between source and destination. Default mode accepts
  ``dest >= source`` (additive); ``--wipe-destination`` requires strict
  equality. Mismatches exit 2 with a stderr diagnostic.
- Progress lines on stderr only (one per batch). No external progress-
  bar dependency — matches the ``seerflow export`` precedent.
- Both backends are closed on exit if they expose ``close()``;
  ``InMemoryIgraphBackend`` does not, so the optional close protocol is
  guarded with ``getattr``.

Out of scope (tracked in follow-ups):

- Live cutover / zero-downtime migration.
- Selective migration (subgraph / time-range / rel-type filters).
- True ``AsyncIterator`` streaming on the source side — the current
  ``export_edges`` returns a list; chunking happens at the CLI layer.
"""
# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import logging
import sys
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from seerflow.config import load_config
from seerflow.graph.factory import connect_graph

if TYPE_CHECKING:
    import argparse

    from seerflow.graph.backends import GraphBackend


GraphBackendName = Literal["igraph", "falkordb", "postgres_age"]

__all__ = ["run_graph_migrate"]

_log = logging.getLogger("seerflow")


_EXIT_OK = 0
_EXIT_BAD_ARGS = 1
_EXIT_VERIFY_FAILED = 2


async def _maybe_close(backend: GraphBackend) -> None:
    """Call ``backend.close()`` if the adapter exposes it.

    ``InMemoryIgraphBackend`` is in-process and has no close contract;
    FalkorDB / Postgres AGE adapters own asyncpg / Redis pools and
    expose an explicit ``close`` coroutine. Guarding with ``getattr``
    keeps the handler Protocol-agnostic.
    """
    close = getattr(backend, "close", None)
    if close is None:
        return
    try:
        await close()
    except Exception as exc:  # pragma: no cover - defensive cleanup path
        _log.warning("error while closing graph backend: %s", exc)


async def _maybe_refresh_counts(backend: GraphBackend) -> None:
    """Call ``backend.refresh_counts()`` if available (FalkorDB / AGE caches).

    The two persistent adapters cache ``vertex_count`` / ``edge_count``
    in Python attributes; the cached values lag the actual server-side
    counters until ``refresh_counts`` is called. ``InMemoryIgraphBackend``
    reads live counts straight from the wrapped ``EntityGraph`` and does
    not implement this method.
    """
    refresh = getattr(backend, "refresh_counts", None)
    if refresh is None:
        return
    await refresh()


def _print_progress(written: int, total: int) -> None:
    """Emit a one-line progress message to stderr."""
    print(f"migrated {written} / {total} edges...", file=sys.stderr)


async def run_graph_migrate(args: argparse.Namespace) -> int:
    """Migrate the entity graph from ``args.from_backend`` to ``args.to_backend``.

    Returns the process exit code: 0 on success, 1 on bad arguments
    (caught at the handler level, not by argparse), 2 on verification
    failure.
    """
    # argparse validates ``--from`` / ``--to`` against the same three-value
    # ``choices=`` tuple that backs ``StorageConfig.graph_backend``; the cast
    # is the documented bridge between argparse's stringly-typed namespace
    # and the dataclass Literal field.
    from_backend = cast("GraphBackendName", args.from_backend)
    to_backend = cast("GraphBackendName", args.to_backend)
    batch_size: int = args.batch_size
    dry_run: bool = args.dry_run
    wipe_destination: bool = args.wipe_destination

    if from_backend == to_backend:
        print(
            f"error: --from and --to must differ (both set to {from_backend!r})",
            file=sys.stderr,
        )
        return _EXIT_BAD_ARGS

    cfg = load_config(args.config)

    source_storage = replace(cfg.storage, graph_backend=from_backend)
    source = await connect_graph(source_storage)

    try:
        rows = await source.export_edges()
        await _maybe_refresh_counts(source)
        source_edge_count = source.edge_count
        source_vertex_count = source.vertex_count
        total = len(rows)

        if dry_run:
            print(
                f"dry-run: source backend {from_backend!r} has "
                f"{source_edge_count} edges, {source_vertex_count} vertices",
            )
            print(f"dry-run: would migrate {total} edges to {to_backend!r}")
            return _EXIT_OK

        dest_storage = replace(cfg.storage, graph_backend=to_backend)
        dest = await connect_graph(dest_storage)

        try:
            if wipe_destination:
                await dest.load([])

            t0 = time.monotonic()
            written = 0
            for chunk_start in range(0, total, batch_size):
                chunk = rows[chunk_start : chunk_start + batch_size]
                for src, tgt, rel, _first, last, _count in chunk:
                    await dest.add_edge(src, tgt, rel, last)
                written += len(chunk)
                _print_progress(written, total)

            await _maybe_refresh_counts(dest)
            elapsed = time.monotonic() - t0

            dest_edge_count = dest.edge_count
            dest_vertex_count = dest.vertex_count

            verify_ok = _verify_counts(
                source_edge_count=source_edge_count,
                source_vertex_count=source_vertex_count,
                dest_edge_count=dest_edge_count,
                dest_vertex_count=dest_vertex_count,
                strict=wipe_destination,
            )
            if not verify_ok:
                print(
                    "error: verification failed — count mismatch after migration "
                    f"(source: {source_edge_count} edges / {source_vertex_count} vertices, "
                    f"dest: {dest_edge_count} edges / {dest_vertex_count} vertices)",
                    file=sys.stderr,
                )
                return _EXIT_VERIFY_FAILED

            print(
                f"migrated {written} edges, {dest_vertex_count} vertices in {elapsed:.2f}s",
            )
            return _EXIT_OK
        finally:
            await _maybe_close(dest)
    finally:
        await _maybe_close(source)


def _verify_counts(
    *,
    source_edge_count: int,
    source_vertex_count: int,
    dest_edge_count: int,
    dest_vertex_count: int,
    strict: bool,
) -> bool:
    """Apply the post-migration count check.

    ``strict`` mode (``--wipe-destination`` set) requires exact
    equality. Default additive mode requires the destination to hold at
    least the source's counts.
    """
    if strict:
        return dest_edge_count == source_edge_count and dest_vertex_count == source_vertex_count
    return dest_edge_count >= source_edge_count and dest_vertex_count >= source_vertex_count
