"""Alert and model state throughput benchmarks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from seerflow.models.query import AlertQuery
from tests.benchmarks.conftest import make_alert

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


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

        assert save_rate >= 5000, f"Model save {save_rate:.0f}/sec below 5000 floor"
        assert load_rate >= 10000, f"Model load {load_rate:.0f}/sec below 10000 floor"
