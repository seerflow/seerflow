"""EventNormalizer throughput benchmarks."""

from __future__ import annotations

import time

from seerflow.parsing.normalizer import EventNormalizer
from seerflow.receivers.base import RawEvent


class TestNormalizerBenchmarks:
    def test_normalize_throughput(self) -> None:
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
        start = time.perf_counter()
        for raw in raws:
            normalizer.normalize(raw)
        elapsed = time.perf_counter() - start
        rate = 10_000 / elapsed
        assert rate >= 5000, f"Normalize {rate:.0f}/sec below 5K floor"
