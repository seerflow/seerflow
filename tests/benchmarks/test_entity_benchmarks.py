"""Performance benchmarks for EntityExtractor."""

from __future__ import annotations

import time

import pytest

from seerflow.parsing.entities import EntityExtractor


class TestEntityBenchmarks:
    @pytest.mark.benchmark
    def test_extraction_throughput(self) -> None:
        ext = EntityExtractor()
        messages = [
            f"Login from 10.0.0.{i % 256} user user{i}"
            f" to /var/log/app{i}.log via host-{i % 50}.example.com"
            for i in range(10_000)
        ]
        start = time.perf_counter()
        for msg in messages:
            ext.extract(msg)
        elapsed = time.perf_counter() - start
        rate = 10_000 / elapsed
        assert rate >= 10_000, f"Entity extraction {rate:.0f}/sec below 10K floor"
