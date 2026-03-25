"""EventNormalizer throughput benchmarks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.parsing.normalizer import EventNormalizer
from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


class TestNormalizerBenchmarks:
    def test_normalize_throughput(self, benchmark: BenchmarkFixture) -> None:
        normalizer = EventNormalizer()
        raws = [
            RawEvent(
                data=f"Login from 10.0.0.{i % 256} user=user{i} on host-{i % 50}".encode(),
                source_type="syslog",
                source_id="bench",
                received_ns=1_710_000_000_000_000_000,
                metadata={},
            )
            for i in range(10_000)
        ]

        def run() -> None:
            for raw in raws:
                normalizer.normalize(raw)

        benchmark(run)
        rate = 10_000 / benchmark.stats["mean"]
        assert rate >= 5_000, f"Normalize {rate:.0f}/sec below 5K floor"
