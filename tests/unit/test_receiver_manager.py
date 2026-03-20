"""Tests for ReceiverManager."""
from __future__ import annotations

import logging

import pytest

from seerflow.receivers.base import RawEvent, Receiver
from seerflow.receivers.manager import ReceiverManager


class _MockReceiver:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.started = False
        self.stopped = False
        self._fail_start = fail_start

    async def start(self) -> None:
        if self._fail_start:
            msg = "start failed"
            raise RuntimeError(msg)
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def is_healthy(self) -> bool:
        return self.started and not self.stopped


class TestReceiverManagerLifecycle:
    def test_register(self) -> None:
        mgr = ReceiverManager()
        receiver = _MockReceiver()
        mgr.register("test-1", receiver)
        assert "test-1" in mgr._receivers

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
