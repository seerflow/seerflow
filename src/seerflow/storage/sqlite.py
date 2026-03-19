"""SQLite storage backend — schema creation and event batch writes.

Implements ``LogStore.write_events`` via aiosqlite with WAL mode.
Schema is auto-created on first run. Events are batched via ``WriteBuffer``
(1000 events or 100ms, whichever first) for high-throughput writes.

See: docs/superpowers/specs/2026-03-18-s006-sqlite-backend-design.md
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class WriteBuffer:
    """Async event buffer with size-threshold and periodic flush.

    The lock protects only the buffer drain — the flush callback runs
    outside the lock so ``append()`` is never blocked by a DB write.
    """

    __slots__ = (
        "_buffer",
        "_callback",
        "_flush_interval",
        "_lock",
        "_max_size",
        "_task",
    )

    def __init__(
        self,
        flush_callback: Callable[[list[Any]], Awaitable[None]],
        max_size: int = 1000,
        flush_interval: float = 0.1,
    ) -> None:
        self._buffer: deque[Any] = deque()
        self._callback = flush_callback
        self._max_size = max_size
        self._flush_interval = flush_interval
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the periodic flush background task."""
        self._task = asyncio.create_task(self._periodic_flush())

    async def append(self, events: list[Any]) -> None:
        """Add events to the buffer; auto-flush if size threshold is reached."""
        self._buffer.extend(events)
        if len(self._buffer) >= self._max_size:
            await self.flush()

    async def flush(self) -> None:
        """Drain the buffer and invoke the flush callback."""
        async with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()
        await self._callback(batch)

    async def close(self) -> None:
        """Cancel periodic task (if running) and flush remaining events."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush()

    async def _periodic_flush(self) -> None:
        """Flush on a timer until cancelled."""
        while True:
            await asyncio.sleep(self._flush_interval)
            await self.flush()
