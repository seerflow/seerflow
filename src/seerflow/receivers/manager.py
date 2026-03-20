"""ReceiverManager — lifecycle orchestrator for all receivers."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from seerflow.receivers.base import Receiver

_log = logging.getLogger(__name__)


class ReceiverManager:
    """Lifecycle manager for all ingestion receivers.

    Usage:
        mgr = ReceiverManager(queue_maxsize=10_000)
        mgr.register("syslog-main", syslog_receiver)
        await mgr.start()
        ...
        event = await mgr.get_event()
        ...
        await mgr.stop()
    """

    __slots__ = ("_queue", "_receivers", "_started", "_stopped")

    def __init__(self, *, queue_maxsize: int = 10_000) -> None:
        self._receivers: dict[str, Receiver] = {}
        self._queue: asyncio.Queue[RawEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._started = False
        self._stopped = False

    def register(self, source_id: str, receiver: Receiver) -> None:
        """Register a receiver for lifecycle management."""
        self._receivers[source_id] = receiver

    async def start(self) -> None:
        """Start all registered receivers."""
        if self._started:
            return
        self._started = True
        for source_id, receiver in self._receivers.items():
            try:
                await receiver.start()
            except Exception:
                _log.exception("Failed to start receiver %s", source_id)

    async def stop(self) -> None:
        """Stop all receivers."""
        if self._stopped:
            return
        self._stopped = True
        for source_id, receiver in self._receivers.items():
            try:
                await receiver.stop()
            except Exception:
                _log.exception("Failed to stop receiver %s", source_id)
