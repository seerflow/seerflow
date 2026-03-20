"""Tests for Receiver Protocol and RawEvent."""
from __future__ import annotations

import pytest

from seerflow.receivers.base import RawEvent, Receiver


class _MockReceiver:
    def __init__(self) -> None:
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    def is_healthy(self) -> bool:
        return self._started


class _NotAReceiver:
    async def do_nothing(self) -> None: ...


class TestRawEvent:
    def test_creation(self) -> None:
        event = RawEvent(
            data=b"test log line",
            source_type="syslog",
            source_id="syslog-main",
            received_ns=1_710_000_000_000_000_000,
            metadata={"ip": "192.168.1.1"},
        )
        assert event.data == b"test log line"
        assert event.source_type == "syslog"
        assert event.received_ns == 1_710_000_000_000_000_000

    def test_frozen(self) -> None:
        event = RawEvent(
            data=b"test", source_type="syslog", source_id="s1",
            received_ns=0, metadata={},
        )
        with pytest.raises(AttributeError):
            event.data = b"changed"  # type: ignore[misc]

    def test_metadata_types(self) -> None:
        event = RawEvent(
            data=b"test", source_type="file_tailer", source_id="f1",
            received_ns=0, metadata={"path": "/var/log/syslog", "line": "42"},
        )
        assert event.metadata["path"] == "/var/log/syslog"


class TestReceiverProtocol:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockReceiver(), Receiver)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAReceiver(), Receiver)

    def test_is_healthy_is_sync(self) -> None:
        receiver = _MockReceiver()
        result = receiver.is_healthy()
        assert result is False  # not started
