"""Performance benchmarks for EntityExtractor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.parsing.entities import EntityExtractor

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


class TestEntityBenchmarks:
    def test_extraction_throughput(self, benchmark: BenchmarkFixture) -> None:
        ext = EntityExtractor()
        messages = [
            f"Login from 10.0.0.{i % 256} user user{i}"
            f" to /var/log/app{i}.log via host-{i % 50}.example.com"
            for i in range(10_000)
        ]

        def run() -> None:
            for msg in messages:
                ext.extract(msg)

        benchmark(run)
