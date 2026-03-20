"""Drain3 throughput benchmarks."""
from __future__ import annotations

import time

import pytest

from seerflow.parsing.drain import DrainParser


class TestDrainBenchmarks:
    def test_parse_throughput(self) -> None:
        """Parse 10K messages — floor 5K/sec."""
        parser = DrainParser()
        messages = [
            f"Login failed for user user{i} from 10.0.0.{i % 256}"
            for i in range(10_000)
        ]
        start = time.perf_counter()
        for msg in messages:
            parser.parse(msg)
        elapsed = time.perf_counter() - start
        rate = 10_000 / elapsed
        assert rate >= 5000, f"Drain parse {rate:.0f}/sec below 5K floor"


@pytest.mark.slow
class TestDrainHeavyweight:
    def test_sustained_100k(self) -> None:
        """100K messages — verify template count bounded."""
        parser = DrainParser(max_clusters=500)
        for i in range(100_000):
            parser.parse(f"Event type {i % 50} from host host-{i % 100} status {i % 3}")
        assert parser.template_count <= 500
