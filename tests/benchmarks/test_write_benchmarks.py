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
