"""Integration tests for FileTailReceiver — full pipeline with real files."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from seerflow.receivers.file_tail import FileTailReceiver
from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from pathlib import Path


class TestFileTailEndToEnd:
    async def test_full_lifecycle_with_checkpoint(self, tmp_path: Path) -> None:
        """Start, tail new lines, stop (saves checkpoint), restart (resumes)."""
        f = tmp_path / "app.log"
        f.write_bytes(b"")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="e2e",
            file_paths=(str(f),),
            checkpoint_dir=str(tmp_path),
            debounce_ms=200,
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            with f.open("ab") as fh:
                fh.write(b"line1\nline2\n")
                fh.flush()
            raw1 = await asyncio.wait_for(mgr._queue.get(), timeout=5.0)
            raw2 = await asyncio.wait_for(mgr._queue.get(), timeout=5.0)
            assert b"line1" in raw1.data
            assert b"line2" in raw2.data
        finally:
            await r.stop()

        # Checkpoint should exist
        cp = tmp_path / "file_offsets.json"
        assert cp.exists()

        # Restart — should NOT re-read old lines
        mgr2 = ReceiverManager(queue_maxsize=100)
        r2 = FileTailReceiver(
            mgr2,
            source_id="e2e",
            file_paths=(str(f),),
            checkpoint_dir=str(tmp_path),
            debounce_ms=200,
        )
        await r2.start()
        await r2.wait_ready()
        try:
            await asyncio.sleep(0.1)
            with f.open("ab") as fh:
                fh.write(b"line3\n")
                fh.flush()
            raw3 = await asyncio.wait_for(mgr2._queue.get(), timeout=5.0)
            assert b"line3" in raw3.data
            # Queue should only have line3, not line1/line2
            assert mgr2._queue.qsize() == 0
        finally:
            await r2.stop()

    async def test_crlf_line_endings(self, tmp_path: Path) -> None:
        """Windows-style CRLF lines are stripped correctly."""
        f = tmp_path / "crlf.log"
        f.write_bytes(b"")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="crlf",
            file_paths=(str(f),),
            debounce_ms=200,
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            with f.open("ab") as fh:
                fh.write(b"hello\r\nworld\r\n")
                fh.flush()
            raw1 = await asyncio.wait_for(mgr._queue.get(), timeout=5.0)
            raw2 = await asyncio.wait_for(mgr._queue.get(), timeout=5.0)
            assert raw1.data == b"hello"
            assert raw2.data == b"world"
        finally:
            await r.stop()
