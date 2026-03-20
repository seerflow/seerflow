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

    async def put_event(self, event: RawEvent) -> bool:
        """Put event in queue. Returns False if queue is full (backpressure)."""
        utilization = self.queue_utilization
        if utilization >= 0.8:
            _log.warning("Queue at %.1f%% utilization", utilization * 100)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    async def get_event(self) -> RawEvent:
        """Get next event from queue (blocks until available)."""
        return await self._queue.get()

    @property
    def queue_depth(self) -> int:
        """Current number of events in the queue."""
        return self._queue.qsize()

    @property
    def queue_utilization(self) -> float:
        """Fraction of queue capacity used (0.0 to 1.0)."""
        if self._queue.maxsize == 0:
            return 0.0
        return self._queue.qsize() / self._queue.maxsize
