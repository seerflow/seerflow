"""Syslog throughput benchmarks."""
from __future__ import annotations

import asyncio
import socket
import time

import pytest

from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.syslog import SyslogReceiver, _parse_syslog


class TestSyslogBenchmarks:
    def test_parse_throughput(self) -> None:
        """Parse 10K syslog messages — floor 50K/sec (parsing is fast)."""
        messages = [
            f"<{i % 192}>1 2026-03-20T04:00:00Z host app {i} - - msg {i}".encode()
            for i in range(10_000)
        ]
        start = time.perf_counter()
        for msg in messages:
            _parse_syslog(msg, "127.0.0.1", "udp")
        elapsed = time.perf_counter() - start
        rate = 10_000 / elapsed
        assert rate >= 50_000, f"Parse throughput {rate:.0f}/sec below 50K floor"

    async def test_udp_receive_throughput(self) -> None:
        """Send 10K UDP datagrams — floor 5K/sec (conservative for CI)."""
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
            start = time.perf_counter()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for offset in range(0, total, batch):
                for msg in messages[offset : offset + batch]:
                    sock.sendto(msg, ("127.0.0.1", port))
                # yield + short sleep lets event loop drain tasks
                await asyncio.sleep(0.01)
            sock.close()
            # Wait for remaining tasks to complete
            await asyncio.sleep(1.0)
            elapsed = time.perf_counter() - start
            received = mgr.queue_depth
            rate = received / elapsed
            assert received >= 9000, f"Only received {received}/10000 — too many drops"
            assert rate >= 5000, f"UDP receive {rate:.0f}/sec below 5K floor"
        finally:
            await receiver.stop()


@pytest.mark.slow
class TestSyslogHeavyweight:
    async def test_udp_sustained_50k(self) -> None:
        """Send 50K messages — verify no drops, measure throughput."""
        mgr = ReceiverManager(queue_maxsize=100_000)
        receiver = SyslogReceiver(mgr, source_id="heavy", udp_port=0, tcp_enabled=False)
        await receiver.start()
        try:
            port = receiver.udp_port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            total = 50_000
            batch = 200
            start = time.perf_counter()
            for offset in range(0, total, batch):
                for i in range(offset, min(offset + batch, total)):
                    sock.sendto(
                        f"<165>1 2026-03-20T04:00:00Z host app {i} - - sustained {i}".encode(),
                        ("127.0.0.1", port),
                    )
                await asyncio.sleep(0.01)  # yield so event loop can drain tasks
            sock.close()
            await asyncio.sleep(3.0)  # generous wait for processing
            elapsed = time.perf_counter() - start
            received = mgr.queue_depth
            rate = received / elapsed
            print(f"\nSustained UDP: {received}/{total} received, {rate:,.0f}/sec")
            assert received >= total * 0.95, f"Dropped too many: {received}/{total}"
        finally:
            await receiver.stop()
