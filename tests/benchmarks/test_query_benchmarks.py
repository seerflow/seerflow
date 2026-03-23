"""Query throughput benchmarks."""
# NOTE: These benchmarks use manual timing (time.perf_counter) because
# pytest-benchmark fixture is incompatible with asyncio event loops.

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.query import EventQuery
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_event

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


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

    async def test_filtered_query_throughput(self, backend: SqliteBackend) -> None:
        """10K events filtered by source_type — floor 1 000 events/sec."""
        events = [make_event(message=f"filter {i}", source_type="syslog") for i in range(10_000)]
        await backend._write_batch(events)
        start = time.perf_counter()
        result = await backend.query_events(EventQuery(source_type="syslog", limit=100))
        elapsed = time.perf_counter() - start
        assert result.total == 10_000
        rate = 10_000 / elapsed if elapsed > 0 else float("inf")
        assert rate >= 1000, f"Filtered query {rate:.0f}/sec below 1000 floor"

    async def test_fts5_search_throughput(self, backend: SqliteBackend) -> None:
        """10K events, FTS5 search — floor 1 000 events/sec."""
        events = [make_event(message=f"authentication failed attempt {i}") for i in range(10_000)]
        await backend._write_batch(events)
        start = time.perf_counter()
        results = await backend.search_text("authentication", 100)
        elapsed = time.perf_counter() - start
        assert len(results) == 100
        rate = 10_000 / elapsed if elapsed > 0 else float("inf")
        assert rate >= 1000, f"FTS5 search {rate:.0f}/sec below 1000 floor"


@pytest.mark.benchmark
class TestSyncQueryBenchmarks:
    """Sync wrappers that use asyncio.run() per iteration via the benchmark fixture."""

    def test_query_throughput_100k(self, benchmark: BenchmarkFixture) -> None:
        """Load 100K events then query first page — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for batch in range(10):
                    events = [make_event(message=f"bench {batch}_{i}") for i in range(10_000)]
                    await b._write_batch(events)
                await b.query_events(EventQuery(limit=100))
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_filtered_query_throughput(self, benchmark: BenchmarkFixture) -> None:
        """10K events filtered by source_type — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                events = [
                    make_event(message=f"filter {i}", source_type="syslog")
                    for i in range(10_000)
                ]
                await b._write_batch(events)
                await b.query_events(EventQuery(source_type="syslog", limit=100))
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_fts5_search_throughput(self, benchmark: BenchmarkFixture) -> None:
        """10K events, FTS5 search — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                events = [
                    make_event(message=f"authentication failed attempt {i}")
                    for i in range(10_000)
                ]
                await b._write_batch(events)
                await b.search_text("authentication", 100)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))
