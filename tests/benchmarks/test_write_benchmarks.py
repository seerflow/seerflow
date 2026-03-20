"""Write throughput benchmarks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from tests.benchmarks.conftest import make_event

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.mark.benchmark
class TestWriteBenchmarks:
    async def test_batch_write_throughput(self, backend: SqliteBackend) -> None:
        """10K events via _write_batch — floor 5 000 events/sec."""
        events = [make_event(message=f"bench {i}") for i in range(10_000)]
        start = time.perf_counter()
        await backend._write_batch(events)
        elapsed = time.perf_counter() - start
        rate = 10_000 / elapsed
        assert rate >= 5000, f"Batch write {rate:.0f}/sec below 5000 floor"

    async def test_individual_write_throughput(self, backend: SqliteBackend) -> None:
        """100 single-event writes via write_events — floor 500 events/sec."""
        events = [make_event(message=f"ind {i}") for i in range(100)]
        start = time.perf_counter()
        for event in events:
            await backend.write_events([event])
            await backend._write_buffer.flush()
        elapsed = time.perf_counter() - start
        rate = 100 / elapsed
        assert rate >= 500, f"Individual write {rate:.0f}/sec below 500 floor"

    async def test_write_buffer_e2e_throughput(self, backend: SqliteBackend) -> None:
        """5K events through WriteBuffer e2e — floor 2 000 events/sec."""
        events = [make_event(message=f"buf {i}") for i in range(5000)]
        start = time.perf_counter()
        await backend.write_events(events)
        await backend._write_buffer.flush()
        elapsed = time.perf_counter() - start
        rate = 5000 / elapsed
        assert rate >= 2000, f"WriteBuffer e2e {rate:.0f}/sec below 2000 floor"
