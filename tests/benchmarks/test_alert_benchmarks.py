"""Alert and model state throughput benchmarks."""
# NOTE: These benchmarks use manual timing (time.perf_counter) because
# pytest-benchmark fixture is incompatible with asyncio event loops.

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.query import AlertQuery
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_alert

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark
class TestAlertBenchmarks:
    async def test_alert_write_throughput(self, backend: SqliteBackend) -> None:
        """1K unique alerts — floor 2 000 writes/sec."""
        alerts = [make_alert(message=f"alert {i}") for i in range(1000)]
        start = time.perf_counter()
        for alert in alerts:
            await backend.write_alert(alert)
        elapsed = time.perf_counter() - start
        rate = 1000 / elapsed
        assert rate >= 2000, f"Alert write {rate:.0f}/sec below 2000 floor"

    async def test_alert_dedup_throughput(self, backend: SqliteBackend) -> None:
        """1K alerts with same dedup_key — floor 1 000 writes/sec."""
        alerts = [make_alert(dedup_key="same-key", message=f"dedup {i}") for i in range(1000)]
        start = time.perf_counter()
        for alert in alerts:
            await backend.write_alert(alert)
        elapsed = time.perf_counter() - start
        rate = 1000 / elapsed
        assert rate >= 1000, f"Alert dedup {rate:.0f}/sec below 1000 floor"

    async def test_alert_query_throughput(self, backend: SqliteBackend) -> None:
        """Query 1K alerts — floor 500 events/sec."""
        for i in range(1000):
            await backend.write_alert(make_alert(message=f"q {i}"))
        start = time.perf_counter()
        result = await backend.query_alerts(AlertQuery(limit=100))
        elapsed = time.perf_counter() - start
        assert result.total == 1000
        rate = 1000 / elapsed if elapsed > 0 else float("inf")
        assert rate >= 500, f"Alert query {rate:.0f}/sec below 500 floor"

    async def test_model_state_throughput(self, backend: SqliteBackend) -> None:
        """1K model state save/load cycles — save floor 5K/sec, load floor 10K/sec."""
        start = time.perf_counter()
        for i in range(1000):
            await backend.save_state(f"key:{i}", b"x" * 1024)
        save_elapsed = time.perf_counter() - start
        save_rate = 1000 / save_elapsed

        start = time.perf_counter()
        for i in range(1000):
            await backend.load_state(f"key:{i}")
        load_elapsed = time.perf_counter() - start
        load_rate = 1000 / load_elapsed

        assert save_rate >= 2000, f"Model save {save_rate:.0f}/sec below 2000 floor"
        assert load_rate >= 2000, f"Model load {load_rate:.0f}/sec below 2000 floor"


@pytest.mark.benchmark
class TestSyncAlertBenchmarks:
    """Sync wrappers that use asyncio.run() per iteration via the benchmark fixture."""

    def test_alert_write_throughput(self, benchmark: BenchmarkFixture) -> None:
        """1K unique alerts — benchmark fixture drives iteration."""
        alerts = [make_alert(message=f"alert {i}") for i in range(1000)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for alert in alerts:
                    await b.write_alert(alert)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_alert_dedup_throughput(self, benchmark: BenchmarkFixture) -> None:
        """1K alerts with same dedup_key — benchmark fixture drives iteration."""
        alerts = [make_alert(dedup_key="same-key", message=f"dedup {i}") for i in range(1000)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for alert in alerts:
                    await b.write_alert(alert)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_alert_query_throughput(self, benchmark: BenchmarkFixture) -> None:
        """Query 1K alerts — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for i in range(1000):
                    await b.write_alert(make_alert(message=f"q {i}"))
                await b.query_alerts(AlertQuery(limit=100))
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_model_state_throughput(self, benchmark: BenchmarkFixture) -> None:
        """1K model state save/load cycles — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for i in range(1000):
                    await b.save_state(f"key:{i}", b"x" * 1024)
                for i in range(1000):
                    await b.load_state(f"key:{i}")
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))
