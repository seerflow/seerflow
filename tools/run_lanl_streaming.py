#!/usr/bin/env python
"""Safe, resumable runner for the LANL billion-event streaming validation.

The doc §4.3 snippet (`run_streaming_validation`) is unsafe for a real
full-dataset run for three reasons this script fixes:

  1. It writes its checkpoints into a `tempfile.TemporaryDirectory()` that is
     deleted when the call returns, so it is NOT resumable across a process
     kill. This uses `resume_streaming_validation_async` with a caller-owned,
     on-disk SQLite state DB that survives a kill and reloads the persisted
     cursor + model state on the next run.
  2. The pipeline logs ~3 WARNING lines per anomaly (ANOMALY / template /
     entities) — billions on the full set. This filters out exactly those,
     keeping genuine warnings/errors (e.g. a corrupt-cursor warning) visible.
  3. The doc prints `r.throughput_eps`, which does not exist and raises
     AttributeError. This prints the real fields.

Throughput is ~390 events/sec (CPU-bound: HSTrees walks + Sigma regex), so the
full 1.61B-event set is ~48 days. The first red-team event is ~58.7M events in
(~42 h); accuracy is a hard 0.0 before then. Run under nohup; if killed, just
re-run the same command and it resumes from the last checkpoint.

Usage:
  # Full resumable run, ANOMALY noise muted, log to a file:
  nohup uv run python tools/run_lanl_streaming.py data/lanl \\
      --state-db data/lanl_run/state.db > data/lanl_run/run.log 2>&1 &

  # Bounded pass (won't reach attacks under ~28M events):
  uv run python tools/run_lanl_streaming.py data/lanl --max-events 2000000

  # Progress of an in-flight run (reads the live cursor; WAL-safe):
  uv run python tools/run_lanl_streaming.py --status \\
      --state-db data/lanl_run/state.db
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Dataset constants for the full LANL cyber1 set, used only by --status to
# render progress. (auth+proc+flows records; dns is not read by the harness.)
TOTAL_EVENTS = 1_607_452_967  # auth 1.051B + proc 426.0M + flows 130.0M
FIRST_ATTACK_EVENTS = 58_655_985  # records before first red-team (LANL t=150885s)
THROUGHPUT_EPS = 390  # measured CPU-bound rate, for rough ETA only

# Prefixes of the per-anomaly WARNING flood emitted by pipeline/handler.py.
_FLOOD_PREFIXES = ("ANOMALY", "template:", "entities:", "message:")


def _out(line: str = "") -> None:
    """Write a line and flush — keeps a nohup'd run.log current."""
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


class _DropAnomaly(logging.Filter):
    """Drop the per-event anomaly flood; keep every other record."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg
        return not (
            isinstance(msg, str) and msg.lstrip().startswith(_FLOOD_PREFIXES)
        )


def _configure_logging() -> None:
    # WARNING+ so genuine problems surface during a multi-day run; the only
    # high-volume source (anomaly triage) is filtered out by message prefix.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("seerflow").addFilter(_DropAnomaly())


async def _connect(state_db: Path):
    from seerflow.config import StorageConfig
    from seerflow.storage import connect_storage

    state_db.parent.mkdir(parents=True, exist_ok=True)
    return await connect_storage(
        StorageConfig(backend="sqlite", sqlite_path=str(state_db))
    )


async def _status(state_db: Path) -> int:
    from seerflow.lanl.streaming import CURSOR_STATE_KEY, _decode_cursor

    if not state_db.exists():
        _out(f"no state DB at {state_db} — run not started")
        return 1
    storage = await _connect(state_db)
    try:
        cursor = _decode_cursor(await storage.load_state(CURSOR_STATE_KEY))
    finally:
        await storage.close()
    if cursor is None:
        _out(f"{state_db}: no checkpoint persisted yet")
        return 0
    ep = cursor.events_processed
    pct = 100 * ep / TOTAL_EVENTS
    _out(f"events_processed : {ep:,} / {TOTAL_EVENTS:,} ({pct:.3f}%)")
    _out(f"per-source rows  : {dict(cursor.positions)}")
    if ep >= FIRST_ATTACK_EVENTS:
        _out(f"attacks          : in window (past first red-team ~{FIRST_ATTACK_EVENTS:,})")
    else:
        rem = FIRST_ATTACK_EVENTS - ep
        eta_h = rem / THROUGHPUT_EPS / 3600
        _out(f"attacks          : NOT reached — ~{rem:,} events (~{eta_h:.1f}h) to first")
    return 0


async def _run(
    dataset_dir: Path,
    state_db: Path,
    checkpoint_interval: int,
    max_events: int | None,
) -> int:
    from seerflow.lanl.streaming import resume_streaming_validation_async

    storage = await _connect(state_db)
    _out(
        f"streaming validation: dataset={dataset_dir} state_db={state_db} "
        f"checkpoint_interval={checkpoint_interval:,} max_events={max_events}"
    )
    _out("(resumable — re-run the same command after a kill to continue)")
    t0 = time.time()
    try:
        result = await resume_streaming_validation_async(
            dataset_dir,
            storage,
            checkpoint_interval=checkpoint_interval,
            max_events=max_events,
        )
    except KeyboardInterrupt:
        _out("\ninterrupted — checkpoint persisted; re-run to resume")
        return 130
    finally:
        await storage.close()

    dt = time.time() - t0
    processed = getattr(result, "total_events_processed", None)
    if processed is not None:
        _out(f"\n=== done in {dt:,.0f}s  ({processed:,} events)")
    else:
        _out(f"\n=== done in {dt:,.0f}s")
    _out(f"precision  {result.precision}")
    _out(f"recall     {result.recall}")
    _out(f"f1         {result.f1_score}")
    _out(f"throughput {result.throughput_events_per_s:,.0f} eps")
    _out(f"latency    {result.mean_event_latency_s * 1e3:.3f} ms/event")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Resumable LANL streaming validation runner"
    )
    p.add_argument("dataset_dir", type=Path, nargs="?", default=Path("data/lanl"))
    p.add_argument(
        "--state-db",
        type=Path,
        default=Path("data/lanl_run/state.db"),
        help="persistent SQLite state DB (survives kills; enables resume)",
    )
    p.add_argument(
        "--checkpoint-interval",
        type=int,
        default=50_000,
        help="persist cursor + model state every N events (default 50000)",
    )
    p.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="cap events this run (default: whole dataset)",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="print progress of an in-flight run from the cursor and exit",
    )
    args = p.parse_args()

    _configure_logging()
    if args.status:
        return asyncio.run(_status(args.state_db))
    return asyncio.run(
        _run(
            args.dataset_dir,
            args.state_db,
            args.checkpoint_interval,
            args.max_events,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
