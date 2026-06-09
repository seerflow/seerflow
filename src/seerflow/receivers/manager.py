"""ReceiverManager — lifecycle orchestrator for all receivers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.receivers.base import RawEvent, Receiver

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

    __slots__ = ("_dropped_count", "_queue", "_receivers", "_started", "_stopped")

    def __init__(self, *, queue_maxsize: int = 10_000) -> None:
        self._receivers: dict[str, Receiver] = {}
        self._queue: asyncio.Queue[RawEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._started = False
        self._stopped = False
        # S-082: cumulative backpressure rejections since process start.
        self._dropped_count = 0

    def register(self, source_id: str, receiver: Receiver, *, replace: bool = True) -> bool:
        """Register a receiver for lifecycle management.

        Returns ``True`` when ``receiver`` is now registered under
        ``source_id``, ``False`` when a collision was rejected.

        ``replace`` controls collision behaviour (S-370 dedup guard):

        * ``True`` (default) — overwrite any receiver already keyed by
          ``source_id``. Preserves the historical contract every built-in
          wiring path relies on (re-register == replace).
        * ``False`` — reject the registration when ``source_id`` is already
          taken: the existing receiver is preserved, a WARNING is logged
          naming the conflict, and ``False`` is returned. Plugin
          registration uses this so a third-party receiver can never silently
          shadow a built-in source.
        """
        if not replace and source_id in self._receivers:
            _log.warning(
                "Receiver registration for '%s' rejected: id already registered",
                source_id,
            )
            return False
        self._receivers[source_id] = receiver
        return True

    async def start(self) -> list[str]:
        """Start all registered receivers. Returns list of failed source_ids."""
        if self._started:
            return []
        self._started = True
        failed: list[str] = []
        for source_id, receiver in self._receivers.items():
            try:
                await receiver.start()
            except PermissionError as exc:
                _log.error(
                    "Failed to start receiver '%s': %s "
                    "(hint: ports below 1024 require root or CAP_NET_BIND_SERVICE)",
                    source_id,
                    exc,
                )
                failed.append(source_id)
            except OSError as exc:
                _log.error(
                    "Failed to start receiver '%s': %s",
                    source_id,
                    exc,
                )
                failed.append(source_id)
            except Exception:
                _log.exception("Failed to start receiver '%s'", source_id)
                failed.append(source_id)
        return failed

    async def stop(self) -> None:
        """Stop all receivers."""
        if self._stopped:
            return
        self._stopped = True
        for source_id, receiver in self._receivers.items():
            try:
                await receiver.stop()
            except PermissionError as exc:
                _log.warning("Error stopping receiver '%s': %s", source_id, exc)
            except Exception:
                _log.warning("Error stopping receiver '%s'", source_id, exc_info=True)

    def _enqueue(self, event: RawEvent) -> bool:
        """Shared enqueue logic with backpressure warning."""
        utilization = self.queue_utilization
        if utilization >= 0.8:
            _log.warning("Queue at %.1f%% utilization", utilization * 100)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped_count += 1
            return False
        return True

    async def put_event(self, event: RawEvent) -> bool:
        """Put event in queue. Returns False if queue is full (backpressure)."""
        return self._enqueue(event)

    def put_event_sync(self, event: RawEvent) -> bool:
        """Synchronous variant of ``put_event`` for use in protocol callbacks."""
        return self._enqueue(event)

    async def get_event(self) -> RawEvent | None:
        """Get next event. Returns None when shutdown is signaled."""
        while not self._stopped:
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
        # Drain remaining events before returning None
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

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

    def bounds(self) -> dict[str, int]:
        """Return the S-082 memory-bounds snapshot."""
        return {
            "current": self._queue.qsize(),
            "max": self._queue.maxsize,
            "evictions": self._dropped_count,
        }
