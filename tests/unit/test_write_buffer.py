"""Tests for WriteBuffer — async event batching with periodic flush."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from seerflow.storage.sqlite import WriteBuffer


class TestWriteBufferFlush:
    @pytest.fixture()
    def recorder(self) -> dict[str, Any]:
        return {"batches": [], "call_count": 0}

    def _make_callback(self, recorder: dict[str, Any]):
        async def callback(batch: list[Any]) -> None:
            recorder["batches"].append(batch)
            recorder["call_count"] += 1

        return callback

    async def test_flush_calls_callback_with_buffer_contents(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=100, flush_interval=999)
        await buf.append(["event_a", "event_b"])
        await buf.flush()
        assert recorder["call_count"] == 1
        assert recorder["batches"] == [["event_a", "event_b"]]

    async def test_flush_clears_buffer(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=100, flush_interval=999)
        await buf.append(["event_a"])
        await buf.flush()
        await buf.flush()
        assert recorder["call_count"] == 1

    async def test_flush_on_size_threshold(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=3, flush_interval=999)
        await buf.append(["a", "b", "c"])
        assert recorder["call_count"] == 1
        assert recorder["batches"] == [["a", "b", "c"]]

    async def test_empty_flush_is_noop(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=100, flush_interval=999)
        await buf.flush()
        assert recorder["call_count"] == 0

    async def test_close_flushes_remaining(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=100, flush_interval=999)
        await buf.append(["event_a"])
        await buf.close()
        assert recorder["call_count"] == 1
        assert recorder["batches"] == [["event_a"]]

    async def test_close_cancels_periodic_task(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=100, flush_interval=0.01)
        buf.start()
        await buf.close()
        assert buf._task is not None
        assert buf._task.cancelled() or buf._task.done()

    async def test_periodic_flush_fires(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=9999, flush_interval=0.05)
        buf.start()
        await buf.append(["event_a"])
        await asyncio.sleep(0.15)
        await buf.close()
        assert recorder["call_count"] >= 1
        assert ["event_a"] in recorder["batches"]

    async def test_concurrent_flush_safe(self, recorder):
        cb = self._make_callback(recorder)
        buf = WriteBuffer(cb, max_size=9999, flush_interval=999)
        await buf.append(["a", "b", "c"])
        await asyncio.gather(buf.flush(), buf.flush())
        total_events = sum(len(b) for b in recorder["batches"])
        assert total_events == 3

    async def test_flush_waits_for_inflight_callback(self) -> None:
        """S-348: flush() must not return while a concurrent callback commit is in flight.

        Reproduces the profile-pipeline flake. The periodic flush task drains the
        buffer and parks inside the (slow) callback before its "commit" lands. A
        second flush() — standing in for the harness's explicit ``storage.flush()``
        — used to acquire the lock, see an empty buffer, and return immediately,
        even though the in-flight callback had not committed yet. The fix makes
        flush() a true barrier: it cannot return until every buffered event's
        callback has completed.
        """
        gate = asyncio.Event()
        committed = {"done": False}
        entered = asyncio.Event()

        async def slow_callback(_batch: list[Any]) -> None:
            entered.set()
            await gate.wait()
            committed["done"] = True

        buf = WriteBuffer(slow_callback, max_size=9999, flush_interval=0.01)
        buf.start()
        await buf.append(["a", "b", "c"])

        # Let the periodic task drain the buffer and park inside slow_callback.
        await asyncio.wait_for(entered.wait(), timeout=1.0)

        # The harness's explicit flush(). It must observe the in-flight commit
        # and wait for it, NOT return early on an empty buffer.
        async def second_flush() -> None:
            await buf.flush()
            # When flush() returns, the in-flight callback MUST have committed.
            assert committed["done"], (
                "flush() returned before the in-flight callback committed — "
                "the S-348 durability barrier is broken"
            )

        flush_task = asyncio.create_task(second_flush())
        # Give second_flush a chance to (wrongly) return early if the bug exists.
        await asyncio.sleep(0.05)
        assert not flush_task.done(), (
            "flush() returned while a callback was still in flight (S-348 race)"
        )

        gate.set()  # release the in-flight callback
        await asyncio.wait_for(flush_task, timeout=1.0)
        await buf.close()
