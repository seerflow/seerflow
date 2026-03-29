"""Query throughput benchmarks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.query import EventQuery
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_event

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


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
                    make_event(message=f"filter {i}", source_type="syslog") for i in range(10_000)
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
                    make_event(message=f"authentication failed attempt {i}") for i in range(10_000)
                ]
                await b._write_batch(events)
                await b.search_text("authentication", 100)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))
