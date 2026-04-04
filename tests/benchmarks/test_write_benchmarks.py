"""Write throughput benchmarks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_event

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark
class TestSyncWriteBenchmarks:
    """Sync wrappers that use asyncio.run() per iteration via the benchmark fixture."""

    def test_batch_write_throughput(self, benchmark: BenchmarkFixture) -> None:
        """10K events via _write_batch — benchmark fixture drives iteration."""
        events = [make_event(message=f"bench {i}") for i in range(10_000)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                await b._write_batch(events)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_individual_write_throughput(self, benchmark: BenchmarkFixture) -> None:
        """100 single-event writes via write_events — benchmark fixture drives iteration."""
        events = [make_event(message=f"ind {i}") for i in range(100)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for event in events:
                    await b.write_events([event])
                    await b.flush()
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_write_buffer_e2e_throughput(self, benchmark: BenchmarkFixture) -> None:
        """5K events through WriteBuffer e2e — benchmark fixture drives iteration."""
        events = [make_event(message=f"buf {i}") for i in range(5000)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                await b.write_events(events)
                await b.flush()
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))
