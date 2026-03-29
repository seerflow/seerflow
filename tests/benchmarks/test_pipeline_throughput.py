"""Full pipeline throughput benchmark.

Measures end-to-end throughput: RawEvent -> Drain3 -> entity extraction
-> ML scoring -> Sigma evaluation -> storage write.

Run sustained test:
    pytest tests/benchmarks/test_pipeline_throughput.py -v -m slow --no-header

Run benchmark-fixture test:
    pytest tests/benchmarks/test_pipeline_throughput.py -v -m benchmark
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

import pytest

from seerflow.config import load_config
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models.query import EventQuery
from seerflow.pipeline.handler import _make_handler
from seerflow.receivers.base import RawEvent
from seerflow.sigma.engine import SigmaEngine
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_benchmark.fixture import BenchmarkFixture

# ---------------------------------------------------------------------------
# Synthetic event generator
# ---------------------------------------------------------------------------

# 10 realistic syslog templates with variation points
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


def generate_events(n: int, *, seed: int = 42) -> list[RawEvent]:
    """Create *n* realistic syslog-format RawEvent objects with variation.

    Uses a seeded RNG for reproducibility while varying templates, IPs,
    users, hosts, and other fields.
    """
    rng = random.Random(seed)  # noqa: S311
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

        # RFC 5424 syslog format: <priority>version timestamp hostname app procid msgid sd msg
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
                source_id="bench-syslog",
                received_ns=base_ns + i * 1_000_000,
                metadata={},
            )
        )

    return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _flush(storage: SqliteBackend) -> None:
    """Flush the write buffer so events are queryable."""
    if storage._write_buffer is not None:
        await storage._write_buffer.flush()


async def _build_pipeline(
    tmp_path: Path,
) -> tuple[SqliteBackend, object, SigmaEngine]:
    """Build a complete pipeline environment for benchmarking."""
    config_yaml = tmp_path / "seerflow.yaml"
    config_yaml.write_text(
        "storage:\n"
        f"  data_dir: {tmp_path}\n"
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

    handler = _make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_engine=sigma,
    )
    return storage, handler, sigma


# ---------------------------------------------------------------------------
# Sustained throughput test (heavyweight / slow)
# ---------------------------------------------------------------------------

_SUSTAINED_COUNT = 60_000
_WARMUP_COUNT = 100


@pytest.mark.slow
class TestPipelineThroughput:
    """Measure sustained end-to-end pipeline throughput."""

    async def test_sustained_throughput(self, tmp_path: Path) -> None:
        """Measure sustained pipeline throughput (target: 10K events/sec).

        Sends 60,000 events through the full pipeline (Drain3 -> entity
        extraction -> ML scoring -> Sigma evaluation -> storage write)
        and reports the achieved throughput.

        This is a validation/measurement test, not a gate — it does NOT
        assert a minimum rate because CI runners vary widely.
        """
        storage, handler, _sigma = await _build_pipeline(tmp_path)

        try:
            events = generate_events(_SUSTAINED_COUNT)

            # Warmup: first N events calibrate ML models (excluded from timing)
            for event in events[:_WARMUP_COUNT]:
                await handler(event)  # type: ignore[operator]

            # Timed run: remaining events
            timed_events = events[_WARMUP_COUNT:]
            timed_count = len(timed_events)

            start = time.perf_counter()
            for event in timed_events:
                await handler(event)  # type: ignore[operator]
            elapsed = time.perf_counter() - start

            rate = timed_count / elapsed if elapsed > 0 else float("inf")

            # Flush and verify storage count
            await _flush(storage)
            result = await storage.query_events(EventQuery(limit=1))
            stored_total = result.total

            print(  # noqa: T201
                f"\n{'=' * 70}\n"
                f"  Pipeline Throughput Benchmark Results\n"
                f"{'=' * 70}\n"
                f"  Total events:    {_SUSTAINED_COUNT:,}\n"
                f"  Warmup events:   {_WARMUP_COUNT:,} (excluded from timing)\n"
                f"  Timed events:    {timed_count:,}\n"
                f"  Elapsed time:    {elapsed:.3f}s\n"
                f"  Throughput:      {rate:,.0f} events/sec (target: 10,000)\n"
                f"  Stored events:   {stored_total:,}\n"
                f"{'=' * 70}"
            )

            # Verify all events were stored (pipeline did not drop any)
            assert stored_total >= _SUSTAINED_COUNT, (
                f"Expected {_SUSTAINED_COUNT:,} stored events, got {stored_total:,}"
            )

        finally:
            await storage.close()


# ---------------------------------------------------------------------------
# Benchmark-fixture test (pytest-benchmark tracked)
# ---------------------------------------------------------------------------

_BATCH_SIZE = 10_000


@pytest.mark.benchmark
class TestPipelineBenchmarkFixture:
    """pytest-benchmark tracked pipeline throughput."""

    def test_pipeline_10k_batch(self, benchmark: BenchmarkFixture, tmp_path: Path) -> None:
        """Benchmark a 10K-event batch through the full pipeline.

        Uses asyncio.run() as a sync wrapper so pytest-benchmark can drive
        iteration and statistics collection.
        """
        events = generate_events(_BATCH_SIZE)

        benchmark.pedantic(_run_sync, args=(events, tmp_path), rounds=3, warmup_rounds=1)

        mean_time = benchmark.stats["mean"]
        rate = _BATCH_SIZE / mean_time if mean_time > 0 else float("inf")
        print(f"\nThroughput: {rate:,.0f} events/sec (target: 10,000)")  # noqa: T201


def _run_sync(events: list[RawEvent], tmp_path: Path) -> None:
    """Sync wrapper that runs a 10K-event batch through the full pipeline."""

    async def _inner() -> None:
        storage, handler, _sigma = await _build_pipeline(tmp_path)
        try:
            for event in events:
                await handler(event)  # type: ignore[operator]
            await _flush(storage)
        finally:
            await storage.close()

    asyncio.run(_inner())
