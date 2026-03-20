"""Heavyweight benchmarks — run with: pytest -m slow -v

These are excluded from default CI runs via addopts = "-m 'not slow'".
"""

from __future__ import annotations

import resource
import time

import pytest

from seerflow.config import StorageConfig
from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_alert, make_event


@pytest.mark.slow
class TestHeavyweight:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_sustained_write_100k(self) -> None:
        """Write 100K events in batches — verify no crash + measure throughput."""
        backend = await self._make_backend()
        try:
            start = time.perf_counter()
            for batch in range(10):
                events = [
                    make_event(message=f"sustained {batch * 10000 + i}") for i in range(10_000)
                ]
                await backend._write_batch(events)
            elapsed = time.perf_counter() - start
            rate = 100_000 / elapsed
            print(f"\nSustained write: {rate:,.0f} events/sec ({elapsed:.2f}s)")  # noqa: T201
            assert rate >= 5000, f"Sustained write {rate:.0f}/sec below 5000 floor"
        finally:
            await backend.close()

    async def test_compound_query_100k(self) -> None:
        """Insert 100K events, query with compound filters."""
        backend = await self._make_backend()
        try:
            for batch in range(10):
                events = [
                    make_event(message=f"compound {batch * 10000 + i}", source_type="syslog")
                    for i in range(10_000)
                ]
                await backend._write_batch(events)
            tr = TimeRange(start_ns=0, end_ns=2_000_000_000_000_000_000)
            start = time.perf_counter()
            result = await backend.query_events(
                EventQuery(time_range=tr, source_type="syslog", severity_min=0, limit=100)
            )
            elapsed = time.perf_counter() - start
            assert result.total == 100_000
            print(f"\nCompound query 100K: {elapsed:.3f}s")  # noqa: T201
            assert elapsed < 10.0, f"Compound query took {elapsed:.2f}s"
        finally:
            await backend.close()

    async def test_alert_dedup_stress_10k(self) -> None:
        """Write 10K alerts with same dedup_key — verify final count."""
        backend = await self._make_backend()
        try:
            start = time.perf_counter()
            for i in range(10_000):
                await backend.write_alert(
                    make_alert(dedup_key="stress-key", message=f"stress {i}")
                )
            elapsed = time.perf_counter() - start
            rate = 10_000 / elapsed

            # Verify dedup count
            result = await backend.query_alerts(AlertQuery())
            assert result.total == 1  # only 1 unique alert
            async with await backend._conn.execute(
                "SELECT dedup_count FROM alerts WHERE dedup_key = 'stress-key'"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None
            assert row[0] == 10_000

            print(f"\nAlert dedup stress: {rate:,.0f} ops/sec ({elapsed:.2f}s)")  # noqa: T201
            assert rate >= 500, f"Dedup stress {rate:.0f}/sec below 500 floor"
        finally:
            await backend.close()

    async def test_memory_stability_100k(self) -> None:
        """Write 100K events, check memory doesn't grow excessively."""
        backend = await self._make_backend()
        try:
            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB on Linux
            for batch in range(10):
                events = [make_event(message=f"mem {batch * 10000 + i}") for i in range(10_000)]
                await backend._write_batch(events)
            rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            delta_mb = (rss_after - rss_before) / 1024  # KB -> MB
            print(  # noqa: T201
                f"\nMemory delta: {delta_mb:.1f} MB"
                f" (before: {rss_before / 1024:.0f} MB, after: {rss_after / 1024:.0f} MB)"
            )
            assert delta_mb < 200, f"Memory grew {delta_mb:.0f} MB — expected < 200 MB"
        finally:
            await backend.close()
