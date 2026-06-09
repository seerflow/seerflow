"""Tests for ReceiverManager."""

from __future__ import annotations

import logging

import pytest

from seerflow.receivers.base import RawEvent
from seerflow.receivers.manager import ReceiverManager


class _MockReceiver:
    def __init__(
        self,
        *,
        fail_start: bool = False,
        fail_start_exc: type[Exception] | None = None,
        fail_stop_exc: type[Exception] | None = None,
    ) -> None:
        self.started = False
        self.stopped = False
        self._fail_start = fail_start
        self._fail_start_exc = fail_start_exc
        self._fail_stop_exc = fail_stop_exc

    async def start(self) -> None:
        if self._fail_start_exc is not None:
            raise self._fail_start_exc("mock start failure")
        if self._fail_start:
            msg = "start failed"
            raise RuntimeError(msg)
        self.started = True

    async def stop(self) -> None:
        if self._fail_stop_exc is not None:
            raise self._fail_stop_exc("mock stop failure")
        self.stopped = True

    def is_healthy(self) -> bool:
        return self.started and not self.stopped


class TestReceiverManagerLifecycle:
    def test_register(self) -> None:
        mgr = ReceiverManager()
        receiver = _MockReceiver()
        mgr.register("test-1", receiver)
        assert "test-1" in mgr._receivers

    def test_register_returns_true_when_id_free(self) -> None:
        mgr = ReceiverManager()
        assert mgr.register("test-1", _MockReceiver()) is True

    def test_register_default_replaces_on_collision(self) -> None:
        mgr = ReceiverManager()
        first = _MockReceiver()
        second = _MockReceiver()
        mgr.register("dup", first)
        assert mgr.register("dup", second) is True
        assert mgr._receivers["dup"] is second  # default replace=True overwrites

    def test_register_guard_rejects_collision_without_overwrite(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        mgr = ReceiverManager()
        first = _MockReceiver()
        second = _MockReceiver()
        mgr.register("dup", first)
        with caplog.at_level(logging.WARNING):
            result = mgr.register("dup", second, replace=False)
        assert result is False
        assert mgr._receivers["dup"] is first  # original preserved
        assert any("dup" in r.message for r in caplog.records)

    def test_register_guard_allows_free_id(self) -> None:
        mgr = ReceiverManager()
        assert mgr.register("fresh", _MockReceiver(), replace=False) is True

    async def test_start_calls_receiver_start(self) -> None:
        mgr = ReceiverManager()
        r1 = _MockReceiver()
        r2 = _MockReceiver()
        mgr.register("r1", r1)
        mgr.register("r2", r2)
        await mgr.start()
        assert r1.started
        assert r2.started
        await mgr.stop()

    async def test_stop_calls_receiver_stop(self) -> None:
        mgr = ReceiverManager()
        r1 = _MockReceiver()
        mgr.register("r1", r1)
        await mgr.start()
        await mgr.stop()
        assert r1.stopped

    async def test_start_idempotent(self) -> None:
        mgr = ReceiverManager()
        mgr.register("r1", _MockReceiver())
        await mgr.start()
        await mgr.start()  # no error
        await mgr.stop()

    async def test_stop_idempotent(self) -> None:
        mgr = ReceiverManager()
        mgr.register("r1", _MockReceiver())
        await mgr.start()
        await mgr.stop()
        await mgr.stop()  # no error

    async def test_start_logs_receiver_errors(self, caplog) -> None:
        mgr = ReceiverManager()
        r_good = _MockReceiver()
        r_bad = _MockReceiver(fail_start=True)
        mgr.register("good", r_good)
        mgr.register("bad", r_bad)
        with caplog.at_level(logging.ERROR):
            await mgr.start()
        assert r_good.started  # good one still started
        assert "bad" in caplog.text or "start failed" in caplog.text
        await mgr.stop()

    async def test_start_permission_error(self, caplog) -> None:
        """PermissionError during start is logged with hint (lines 50-56)."""
        mgr = ReceiverManager()
        r = _MockReceiver(fail_start_exc=PermissionError)
        mgr.register("priv-port", r)
        with caplog.at_level(logging.ERROR):
            failed = await mgr.start()
        assert "priv-port" in failed
        assert "CAP_NET_BIND_SERVICE" in caplog.text or "priv-port" in caplog.text
        await mgr.stop()

    async def test_start_os_error(self, caplog) -> None:
        """OSError during start is logged (lines 58-63)."""
        mgr = ReceiverManager()
        r = _MockReceiver(fail_start_exc=OSError)
        mgr.register("bind-fail", r)
        with caplog.at_level(logging.ERROR):
            failed = await mgr.start()
        assert "bind-fail" in failed
        await mgr.stop()

    async def test_stop_permission_error(self, caplog) -> None:
        """PermissionError during stop is logged as warning (line 78)."""
        mgr = ReceiverManager()
        r = _MockReceiver(fail_stop_exc=PermissionError)
        r.started = True  # pretend it started
        mgr.register("perm-stop", r)
        mgr._started = True
        with caplog.at_level(logging.WARNING):
            await mgr.stop()
        assert "perm-stop" in caplog.text


def _make_event(source_id: str = "test") -> RawEvent:
    return RawEvent(
        data=b"test log",
        source_type="test",
        source_id=source_id,
        received_ns=1_710_000_000_000_000_000,
        metadata={},
    )


class TestQueueAndBackpressure:
    async def test_put_event_adds_to_queue(self) -> None:
        mgr = ReceiverManager(queue_maxsize=100)
        event = _make_event()
        result = await mgr.put_event(event)
        assert result is True
        assert mgr.queue_depth == 1

    async def test_get_event_returns_from_queue(self) -> None:
        mgr = ReceiverManager(queue_maxsize=100)
        event = _make_event()
        await mgr.put_event(event)
        got = await mgr.get_event()
        assert got is event

    async def test_queue_depth(self) -> None:
        mgr = ReceiverManager(queue_maxsize=100)
        assert mgr.queue_depth == 0
        await mgr.put_event(_make_event())
        assert mgr.queue_depth == 1
        await mgr.put_event(_make_event())
        assert mgr.queue_depth == 2

    async def test_queue_utilization(self) -> None:
        mgr = ReceiverManager(queue_maxsize=10)
        assert mgr.queue_utilization == 0.0
        for _ in range(5):
            await mgr.put_event(_make_event())
        assert mgr.queue_utilization == pytest.approx(0.5)

    async def test_backpressure_full_returns_false(self) -> None:
        mgr = ReceiverManager(queue_maxsize=2)
        await mgr.put_event(_make_event())
        await mgr.put_event(_make_event())
        result = await mgr.put_event(_make_event())  # queue full
        assert result is False
        assert mgr.queue_depth == 2

    async def test_backpressure_80pct_logs_warning(self, caplog) -> None:
        mgr = ReceiverManager(queue_maxsize=10)
        for _ in range(8):
            await mgr.put_event(_make_event())
        with caplog.at_level(logging.WARNING):
            await mgr.put_event(_make_event())  # 9th item = 90%
        assert "utilization" in caplog.text.lower() or "90" in caplog.text

    async def test_put_event_normal_returns_true(self) -> None:
        mgr = ReceiverManager(queue_maxsize=100)
        result = await mgr.put_event(_make_event())
        assert result is True


class TestGracefulShutdown:
    async def test_stop_preserves_queue_events(self) -> None:
        mgr = ReceiverManager(queue_maxsize=100)
        mgr.register("r1", _MockReceiver())
        await mgr.start()
        await mgr.put_event(_make_event())
        await mgr.put_event(_make_event())
        await mgr.stop()
        # Events should still be in queue after stop
        assert mgr.queue_depth == 2

    async def test_start_stop_no_receivers(self) -> None:
        mgr = ReceiverManager()
        await mgr.start()
        await mgr.stop()  # no error with empty receivers

    async def test_get_event_returns_none_after_stop(self) -> None:
        mgr = ReceiverManager()
        await mgr.stop()
        result = await mgr.get_event()
        assert result is None

    async def test_get_event_drains_before_none(self) -> None:
        mgr = ReceiverManager()
        event = RawEvent(
            data=b"test", source_type="test", source_id="t", received_ns=0, metadata={}
        )
        await mgr.put_event(event)
        await mgr.stop()
        result = await mgr.get_event()
        assert result is not None
        assert result.data == b"test"
        result2 = await mgr.get_event()
        assert result2 is None

    async def test_get_event_drains_multiple_before_none(self) -> None:
        mgr = ReceiverManager()
        for i in range(5):
            event = RawEvent(
                data=f"evt-{i}".encode(),
                source_type="test",
                source_id="t",
                received_ns=i,
                metadata={},
            )
            await mgr.put_event(event)
        await mgr.stop()
        drained = []
        while True:
            result = await mgr.get_event()
            if result is None:
                break
            drained.append(result)
        assert len(drained) == 5
        assert drained[0].data == b"evt-0"
        assert drained[4].data == b"evt-4"


class TestExports:
    def test_imports(self) -> None:
        import seerflow.receivers as receivers_mod

        assert hasattr(receivers_mod, "RawEvent")
        assert hasattr(receivers_mod, "Receiver")
        assert hasattr(receivers_mod, "ReceiverManager")

    def test_all(self) -> None:
        import seerflow.receivers as mod

        expected = {
            "FileTailReceiver",
            "OtlpGrpcReceiver",
            "OtlpHttpReceiver",
            "RawEvent",
            "Receiver",
            "ReceiverManager",
            "StdinReceiver",
            "SyslogReceiver",
            "WebhookConfig",
            "WebhookReceiver",
        }
        assert set(mod.__all__) == expected
