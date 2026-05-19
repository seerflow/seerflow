"""Streaming stdin receiver (S-316, FR-082).

Lets piped datasets and ``docker logs``/``kubectl logs`` output stream
straight into the live :class:`~seerflow.pipeline.Pipeline` while it runs
under ``seerflow start``. Complements the finite batch stdin path in
``seerflow analyze -`` (FR-070): this is the long-running, line-oriented
receiver that participates in the normal :class:`Receiver` lifecycle.

stdin is a blocking fd by default. The default line source uses
``loop.connect_read_pipe`` + ``asyncio.StreamReader`` so reads never block
the event loop (the dashboard and other receivers keep running). A
``<``-redirected regular file is rejected by ``connect_read_pipe`` on some
platforms, so a threaded ``run_in_executor`` blocking-readline fallback
keeps production robust whether stdin is a true pipe or a redirect. The
fallback's blocked ``readline`` is uninterruptible by ``stop()`` (a
C-level read); it unblocks on EOF — the normal end state for a piped
source (``cat``/``docker logs`` closes its end) — or at process exit.

EOF semantics are receiver-scoped, matching ``SyslogReceiver`` and
``FileTailReceiver``: on EOF the read task ends cleanly, ``stop()`` is
idempotent, and ``is_healthy()`` flips to ``False``. Process-level shutdown
stays signal-driven (``_run_with_config``); EOF does not stop the daemon.

NOT thread-safe — create one instance per event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
from typing import TYPE_CHECKING

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from typing import BinaryIO

    from seerflow.receivers.manager import ReceiverManager

_log = logging.getLogger(__name__)

# 1 MB per-line cap — same value as FileTailReceiver._MAX_LINE_BYTES.
# Bounds a single pathological line so a malformed stream cannot exhaust
# memory; oversized lines are dropped with a warning.
_MAX_LINE_BYTES = 1024 * 1024


async def _stream_reader_lines(read_fd: int) -> AsyncIterator[bytes]:
    """Yield lines from *read_fd* via a non-blocking ``StreamReader``.

    Falls back to a threaded blocking ``readline`` when ``connect_read_pipe``
    rejects the fd (a ``<`` redirect is a regular file; a true ``|`` pipe is
    not — platforms differ on which they accept). A line exceeding the
    ``StreamReader`` limit makes ``readline`` raise ``ValueError`` *after*
    self-draining the offending line from its buffer; we log and skip it so
    a single huge line cannot wedge the reader.
    """
    loop = asyncio.get_running_loop()
    pipe = os.fdopen(read_fd, "rb", buffering=0)
    try:
        reader = asyncio.StreamReader(limit=_MAX_LINE_BYTES)
        protocol = asyncio.StreamReaderProtocol(reader)
        try:
            await loop.connect_read_pipe(lambda: protocol, pipe)
        except (ValueError, OSError) as exc:
            _log.debug(
                "connect_read_pipe rejected stdin (%s); using executor fallback",
                exc,
            )
            async for line in _executor_lines(loop, pipe):
                yield line
            return
        while True:
            try:
                line = await reader.readline()
            except ValueError:
                # ``StreamReader.readline`` raises ``ValueError`` when a line
                # exceeds ``limit``; it has *already* drained the offending
                # line (up to + including its newline, or cleared the buffer
                # on a partial). Just warn and resume with the next line — no
                # manual buffer surgery, no busy-loop.
                _log.warning(
                    "Discarding oversized stdin line (exceeds %d bytes)",
                    _MAX_LINE_BYTES,
                )
                continue
            if not line:
                return
            yield line
    finally:
        with contextlib.suppress(OSError):
            pipe.close()


async def _executor_lines(loop: asyncio.AbstractEventLoop, pipe: BinaryIO) -> AsyncIterator[bytes]:
    """Threaded blocking ``readline`` fallback yielding one line at a time."""
    while True:
        line: bytes = await loop.run_in_executor(None, pipe.readline)
        if not line:
            return
        yield line


class StdinReceiver:
    """Stream newline-delimited stdin into the pipeline as RawEvents.

    Each non-blank line becomes a ``RawEvent`` with ``source_type="stdin"``.
    Trailing ``\\r``/``\\n`` is stripped from ``data``. Lines beyond
    :data:`_MAX_LINE_BYTES` are discarded with a warning. On EOF the read
    task ends cleanly and the receiver marks itself stopped.
    """

    __slots__ = (
        "_drained",
        "_line_source",
        "_manager",
        "_read_task",
        "_source_id",
        "_started",
        "_stopped",
    )

    def __init__(
        self,
        manager: ReceiverManager,
        *,
        source_id: str = "stdin",
        line_source: Callable[[], AsyncIterator[bytes]] | None = None,
    ) -> None:
        self._manager = manager
        self._source_id = source_id
        self._line_source: Callable[[], AsyncIterator[bytes]] = (
            line_source if line_source is not None else self._default_line_source
        )
        self._started = False
        self._stopped = False
        self._read_task: asyncio.Task[None] | None = None
        self._drained: asyncio.Event = asyncio.Event()

    @staticmethod
    def _default_line_source() -> AsyncIterator[bytes]:
        """Real stdin line source: non-blocking pipe read with fallback."""
        return _stream_reader_lines(sys.stdin.fileno())

    @staticmethod
    def pipe_line_source(read_fd: int) -> Callable[[], AsyncIterator[bytes]]:
        """Factory binding the non-blocking reader to an explicit *read_fd*.

        Used by integration tests (and any caller wiring an ``os.pipe()``)
        so the exact production read path is exercised against a real fd.
        """
        return lambda: _stream_reader_lines(read_fd)

    async def start(self) -> None:
        """Spawn the background read task. Idempotent."""
        if self._started:
            return
        self._started = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Consume the line source, emitting non-blank lines as RawEvents."""
        try:
            async for raw in self._line_source():
                stripped = raw.rstrip(b"\r\n")
                if not stripped.strip():
                    continue
                if len(stripped) > _MAX_LINE_BYTES:
                    _log.warning(
                        "Discarding oversized stdin line (%d bytes)",
                        len(stripped),
                    )
                    continue
                await self._manager.put_event(
                    RawEvent(
                        data=stripped,
                        source_type="stdin",
                        source_id=self._source_id,
                        received_ns=time.time_ns(),
                        metadata={},
                    )
                )
        except asyncio.CancelledError:
            raise
        finally:
            self._stopped = True
            self._drained.set()

    async def stop(self) -> None:
        """Cancel the read task and mark stopped. Idempotent + start-safe."""
        if self._stopped:
            self._stopped = True
            self._drained.set()
            return
        self._stopped = True
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        self._drained.set()

    def is_healthy(self) -> bool:
        """True only while started and not yet stopped (EOF flips this)."""
        return self._started and not self._stopped

    async def wait_drained(self, timeout: float = 5.0) -> None:
        """Block until the read loop has finished (EOF or stop). Test aid."""
        await asyncio.wait_for(self._drained.wait(), timeout=timeout)
