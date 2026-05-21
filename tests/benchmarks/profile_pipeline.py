"""S-084 — Performance profiling harness for the Seerflow pipeline.

A thin wrapper around the existing 10K events/sec pipeline benchmark
(``tests/benchmarks/test_pipeline_throughput.py``) that exists so external
profilers (py-spy, memray) can wrap a single Python entry point. Re-uses
the same synthetic event generator and pipeline builder as the benchmark,
so the call graph the profiler sees is the same as the call graph S-033
measured.

Usage
-----

Capture a CPU flame graph (py-spy, sampling, low overhead)::

    uv run py-spy record -o profiling/cpu.svg -- \
        uv run python tests/benchmarks/profile_pipeline.py cpu --count 30000

Capture an allocation flame graph (memray, ~2x overhead)::

    uv run memray run -o profiling/mem.bin \
        tests/benchmarks/profile_pipeline.py mem --count 30000
    uv run memray flamegraph profiling/mem.bin -o profiling/mem.html

Quick throughput measurement (no profiler)::

    uv run python tests/benchmarks/profile_pipeline.py bench --count 30000

The three modes (``cpu``, ``mem``, ``bench``) run the same pipeline; the
mode name is only used to label stdout output. All real profiling is
driven by the outer ``py-spy`` / ``memray`` process.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from seerflow.config import load_config
from seerflow.correlation.holders import EngineHolder
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models.query import EventQuery
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent
from seerflow.sigma.engine import SigmaEngine
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------------------
# Synthetic event generator — mirrors tests/benchmarks/test_pipeline_throughput.py
# ---------------------------------------------------------------------------

_TEMPLATES: tuple[str, ...] = (
    "Accepted password for {user} from {ip} port {port} ssh2",
    "Failed password for {user} from {ip} port {port} ssh2",
    "Connection closed by authenticating user {user} {ip} port {port}",
    "error: maximum authentication attempts exceeded for {user} from {ip}",
    "GET /api/v1/{path} HTTP/1.1 200 {ms}ms",
    "POST /api/v1/{path} HTTP/1.1 201 {ms}ms",
    "CRON[{pid}]: ({user}) CMD ({cmd})",
    "kernel: [{ts}] TCP: request_sock_TCP: Possible SYN flooding on port {port}",
    "systemd[1]: Started {service}.service - {desc}",
    "Out of memory: Killed process {pid} ({proc}) total-vm:{vm}kB",
)

_USERS: tuple[str, ...] = ("admin", "root", "deploy", "www-data", "jenkins", "ubuntu")
_HOSTS: tuple[str, ...] = ("web-01", "web-02", "db-01", "app-01", "worker-03", "cache-01")
_PATHS: tuple[str, ...] = ("health", "users", "events", "metrics", "status", "logs")
_SERVICES: tuple[str, ...] = ("nginx", "postgresql", "redis", "celery", "gunicorn")
_CMDS: tuple[str, ...] = ("/usr/bin/logrotate /etc/logrotate.conf", "/opt/backup.sh", "sync")
_PROCS: tuple[str, ...] = ("java", "python3", "node", "redis-server", "postgres")


def build_events(n: int, *, seed: int = 42) -> list[RawEvent]:
    """Create ``n`` realistic syslog-format RawEvent objects with variation.

    Deterministic for a given seed — same seed produces byte-identical
    payloads, which is what makes before/after profile comparisons valid.
    """
    rng = random.Random(seed)  # noqa: S311 -- not cryptographic
    base_ns = 1_710_000_000_000_000_000
    events: list[RawEvent] = []

    for i in range(n):
        template = rng.choice(_TEMPLATES)
        user = rng.choice(_USERS)
        ip = f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
        host = rng.choice(_HOSTS)
        port = rng.randint(1024, 65535)

        body = template.format(
            user=user,
            ip=ip,
            port=port,
            path=rng.choice(_PATHS),
            ms=rng.randint(1, 500),
            pid=rng.randint(1000, 99999),
            cmd=rng.choice(_CMDS),
            ts=f"{rng.uniform(0, 999):.6f}",
            service=rng.choice(_SERVICES),
            desc=f"Service {rng.choice(_SERVICES)}",
            proc=rng.choice(_PROCS),
            vm=rng.randint(100_000, 9_999_999),
        )

        pri = rng.choice((134, 131, 139, 133, 132))
        hour = rng.randint(0, 23)
        minute = rng.randint(0, 59)
        second = rng.randint(0, 59)
        message = (
            f"<{pri}>1 2026-03-28T{hour:02d}:{minute:02d}:{second:02d}Z "
            f"{host} sshd {rng.randint(100, 99999)} - - {body}"
        )

        events.append(
            RawEvent(
                data=message.encode(),
                source_type="syslog",
                source_id="profile-syslog",
                received_ns=base_ns + i * 1_000_000,
                metadata={},
            )
        )

    return events


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


async def _build_pipeline(data_dir: Path) -> tuple[SqliteBackend, object]:
    """Build a complete pipeline environment, mirroring the benchmark fixture."""
    config_yaml = data_dir / "seerflow.yaml"
    config_yaml.write_text(
        "storage:\n"
        f"  data_dir: {data_dir}\n"
        "receivers:\n"
        "  syslog_enabled: false\n"
        "  otlp_grpc_enabled: false\n"
        "  otlp_http_enabled: false\n"
        "  webhook_enabled: false\n"
    )
    config = load_config(str(config_yaml))
    storage = await SqliteBackend.connect(config.storage)
    ensemble = DetectionEnsemble(config.detection)
    sigma = SigmaEngine()
    sigma.load_bundled()

    handler = make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_holder=EngineHolder(engine=sigma),
    )
    return storage, handler


async def _run(events: Sequence[RawEvent], data_dir: Path) -> tuple[float, int]:
    """Push events through a freshly built pipeline, return (elapsed_s, stored_n)."""
    storage, handler = await _build_pipeline(data_dir)
    try:
        start = time.perf_counter()
        for event in events:
            await handler(event)  # type: ignore[operator]
        elapsed = time.perf_counter() - start

        await storage.flush()
        result = await storage.query_events(EventQuery(limit=1))
        stored = result.total
    finally:
        await storage.close()
    return elapsed, stored


def run_pipeline(events: Sequence[RawEvent], data_dir: Path) -> tuple[float, int]:
    """Synchronous wrapper around the async pipeline driver.

    Returns
    -------
    tuple[float, int]
        ``(elapsed_seconds, stored_event_count)``.
    """
    return asyncio.run(_run(events, data_dir))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_VALID_MODES = ("cpu", "mem", "bench")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="profile_pipeline",
        description="Run the Seerflow pipeline under a profiler (py-spy / memray).",
    )
    parser.add_argument(
        "mode",
        choices=_VALID_MODES,
        help="cpu (py-spy outer wrapper), mem (memray outer wrapper), or bench (no profiler).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=30_000,
        help="Number of synthetic events to push through the pipeline (default: 30000).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for event generation; same seed -> same payloads (default: 42).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory for the SQLite backing store. Defaults to a tempdir.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    events = build_events(args.count, seed=args.seed)

    if args.data_dir is None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            elapsed, stored = run_pipeline(events, data_dir)
    else:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        elapsed, stored = run_pipeline(events, args.data_dir)

    rate = args.count / elapsed if elapsed > 0 else float("inf")
    print(  # noqa: T201 -- this is a CLI, stdout is the contract
        f"[{args.mode}] events={args.count:,} elapsed={elapsed:.3f}s "
        f"rate={rate:,.0f} events/sec stored={stored:,}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
