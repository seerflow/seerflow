#!/usr/bin/env python
"""S-356 repeatable per-event throughput micro-benchmark.

Measures the **per-event detection hot path**, which is what S-356 optimizes —
NOT one-time setup (storage connect, Sigma rule YAML load, model seed). Those
amortize on a real 50k/1.6B-event run; on the tiny 137-event committed fixture
they dominate, so a whole-``run_validation`` wall-time is pure setup noise and
would hide (or invert) a genuine per-event win.

Strategy: build the rebased LANL ``RawEvent`` stream once, assemble the full
detection handler once (under the deterministic frozen replay clock so window
pruning / risk decay are stable), warm the models with one pass, then time
``--passes`` further passes that drive every event through ``assembled.handler``.
Throughput = (events driven in timed passes) / (timed-pass wall time). Setup is
excluded by construction.

Deterministic: same fixture, same rebase, frozen clock. Run it before and after
a change to isolate the hot-path delta.

Usage::

    uv run python tests/perf/bench_s356_throughput.py [--passes N] [--dataset DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path


async def _measure_async(dataset: Path, passes: int) -> tuple[int, int, float, float]:
    """Return ``(events_per_pass, timed_events, timed_elapsed_s, eps)``.

    One untimed warmup pass primes the detectors; ``passes`` timed passes
    then drive the same event stream through the assembled handler.
    """
    import tempfile

    from seerflow.config import SeerflowConfig, StorageConfig
    from seerflow.lanl import validator
    from seerflow.lanl.parser import (
        parse_auth_line,
        parse_flow_line,
        parse_proc_line,
    )
    from seerflow.lanl.validator import REPLAY_EPOCH_NS, REPLAY_HEADROOM_NS, _build_raw_events, _rebased
    from seerflow.pipeline.assembly import assemble_handler
    from seerflow.storage import connect_storage

    def _read_lines(filename: str) -> list[str]:
        p = dataset / filename
        if not p.exists():
            return []
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    auth = [parse_auth_line(ln) for ln in _read_lines("auth.csv")]
    proc = [parse_proc_line(ln) for ln in _read_lines("proc.csv")]
    flow = [parse_flow_line(ln) for ln in _read_lines("flows.csv")]
    raw_events = _build_raw_events(auth, proc, flow)
    if not raw_events:
        return 0, 0, 0.0, 0.0

    # Same deterministic rebase as run_validation_async (frozen replay epoch).
    max_ts = max(r.received_ns for r in raw_events)
    offset_ns = REPLAY_EPOCH_NS - max_ts - REPLAY_HEADROOM_NS
    raw_events = sorted(
        (_rebased(r, offset_ns) for r in raw_events),
        key=lambda r: r.received_ns,
    )
    n = len(raw_events)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = await connect_storage(
            StorageConfig(backend="sqlite", sqlite_path=f"{tmpdir}/bench.db")
        )
        try:
            assembled = await assemble_handler(
                SeerflowConfig(), storage, clock_ns=lambda: REPLAY_EPOCH_NS
            )
            try:
                # Warmup pass (untimed) — primes detectors / templates / rules.
                for raw in raw_events:
                    await assembled.handler(raw)

                t0 = time.perf_counter()
                for _ in range(passes):
                    for raw in raw_events:
                        await assembled.handler(raw)
                elapsed = time.perf_counter() - t0
            finally:
                await assembled.teardown()
        finally:
            await storage.close()

    timed_events = n * passes
    eps = timed_events / elapsed if elapsed > 0 else 0.0
    # Reference validator import keeps the module dependency explicit for callers
    # auditing what stack this drives.
    assert validator.REPLAY_EPOCH_NS == REPLAY_EPOCH_NS
    return n, timed_events, elapsed, eps


def _measure(dataset: Path, passes: int) -> tuple[int, int, float, float]:
    """Synchronous wrapper around :func:`_measure_async`."""
    logging.disable(logging.CRITICAL)  # silence per-event logging noise
    return asyncio.run(_measure_async(dataset, passes))


def _main() -> int:
    parser = argparse.ArgumentParser(description="S-356 per-event throughput micro-benchmark")
    parser.add_argument("--passes", type=int, default=40)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("tests/fixtures/lanl"),
    )
    args = parser.parse_args()

    n, timed_events, elapsed, eps = _measure(args.dataset, args.passes)
    print(  # noqa: T201 -- CLI output is the point of this script.
        f"events_per_pass={n} passes={args.passes} "
        f"timed_events={timed_events} timed_elapsed_s={elapsed:.4f} "
        f"per_event_eps={eps:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
