"""Query throughput benchmarks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from seerflow.models.query import EventQuery
from tests.benchmarks.conftest import make_event

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.mark.benchmark
class TestQueryBenchmarks:
    async def test_query_throughput_100k(self, backend: SqliteBackend) -> None:
        """Load 100K events, query first page — floor 2 000 events/sec."""
        for batch in range(10):
            events = [make_event(message=f"bench {batch}_{i}") for i in range(10_000)]
            await backend._write_batch(events)
        start = time.perf_counter()
        result = await backend.query_events(EventQuery(limit=100))
        elapsed = time.perf_counter() - start
        assert result.total == 100_000
        rate = 100_000 / elapsed if elapsed > 0 else float("inf")
        assert rate >= 2000, f"Query throughput {rate:.0f}/sec below 2000 floor"
