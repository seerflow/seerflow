"""File reader throughput benchmarks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.receivers.file_tail import _read_new_lines

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_benchmark.fixture import BenchmarkFixture


class TestFileTailBenchmarks:
    def test_file_read_throughput(self, benchmark: BenchmarkFixture, tmp_path: Path) -> None:
        """Read 10K lines from a file — floor 50K lines/sec."""
        f = tmp_path / "bench.log"
        lines = [f"log line {i} from host-{i % 50} user=user{i}\n" for i in range(10_000)]
        f.write_text("".join(lines))

        def run() -> None:
            _read_new_lines(f, 0)

        benchmark(run)
        rate = 10_000 / benchmark.stats["mean"]
        assert rate >= 50_000, f"File read {rate:.0f} lines/sec below 50K floor"
