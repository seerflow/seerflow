"""Alert and model state throughput benchmarks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.query import AlertQuery
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_alert

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


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
