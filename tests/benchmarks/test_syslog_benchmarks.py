"""Syslog throughput benchmarks."""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

import pytest

from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.syslog import SyslogReceiver, _parse_syslog

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


class TestSyslogBenchmarks:
    def test_parse_throughput(self, benchmark: BenchmarkFixture) -> None:
        """Parse 10K syslog messages — floor 50K/sec (parsing is fast)."""
        messages = [
            f"<{i % 192}>1 2026-03-20T04:00:00Z host app {i} - - msg {i}".encode()
            for i in range(10_000)
        ]

        def run() -> None:
            for msg in messages:
                _parse_syslog(msg, "127.0.0.1", "udp")

        benchmark(run)
        rate = 10_000 / benchmark.stats["mean"]
        assert rate >= 50_000, f"Parse throughput {rate:.0f}/sec below 50K floor"


@pytest.mark.benchmark
class TestSyncSyslogBenchmarks:
    """Sync wrappers that use asyncio.run() per iteration via the benchmark fixture."""

    def test_udp_receive_throughput(self, benchmark: BenchmarkFixture) -> None:
        """Send 10K UDP datagrams — benchmark fixture drives iteration."""

        async def _run() -> None:
            mgr = ReceiverManager(queue_maxsize=20_000)
            receiver = SyslogReceiver(mgr, source_id="bench", udp_port=0, tcp_enabled=False)
            await receiver.start()
            try:
                port = receiver.udp_port
                total = 10_000
                batch = 200
                messages = [
                    f"<165>1 2026-03-20T04:00:00Z host app {i} - - bench msg {i}".encode()
                    for i in range(total)
                ]
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    for offset in range(0, total, batch):
                        for msg in messages[offset : offset + batch]:
                            sock.sendto(msg, ("127.0.0.1", port))
                        await asyncio.sleep(0.01)
                # wait for event loop to drain remaining tasks
                await asyncio.sleep(1.0)
            finally:
                await receiver.stop()

        benchmark(lambda: asyncio.run(_run()))

    @pytest.mark.slow
    def test_udp_sustained_50k(self, benchmark: BenchmarkFixture) -> None:
        """Send 50K messages — benchmark fixture drives iteration."""

        async def _run() -> None:
            mgr = ReceiverManager(queue_maxsize=100_000)
            receiver = SyslogReceiver(mgr, source_id="heavy", udp_port=0, tcp_enabled=False)
            await receiver.start()
            try:
                port = receiver.udp_port
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    total = 50_000
                    batch = 200
                    for offset in range(0, total, batch):
                        for i in range(offset, min(offset + batch, total)):
                            msg = f"<165>1 2026-03-20T04:00:00Z host app {i} - - sustained {i}"
                            sock.sendto(msg.encode(), ("127.0.0.1", port))
                        await asyncio.sleep(0.01)
                # wait for event loop to drain remaining tasks
                await asyncio.sleep(3.0)
            finally:
                await receiver.stop()

        benchmark(lambda: asyncio.run(_run()))
