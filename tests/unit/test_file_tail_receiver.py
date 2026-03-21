"""Tests for FileTailReceiver — file tailing, rotation, checkpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from seerflow.receivers.base import Receiver
from seerflow.receivers.file_tail import (
    FileOffset,
    FileTailReceiver,
    _check_rotation,
    _load_checkpoint,
    _read_new_lines,
    _save_checkpoint,
)
from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from pathlib import Path


class TestCheckpoint:
    def test_save_and_load(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        offsets = {"/var/log/syslog": FileOffset(offset=100, inode=12345)}
        _save_checkpoint(cp_file, offsets)
        loaded = _load_checkpoint(cp_file)
        assert loaded["/var/log/syslog"].offset == 100
        assert loaded["/var/log/syslog"].inode == 12345

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "nonexistent.json"
        assert _load_checkpoint(cp_file) == {}

    def test_checkpoint_multiple_files(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        offsets = {
            "/var/log/a.log": FileOffset(offset=10, inode=1),
            "/var/log/b.log": FileOffset(offset=20, inode=2),
        }
        _save_checkpoint(cp_file, offsets)
        loaded = _load_checkpoint(cp_file)
        assert len(loaded) == 2

    def test_atomic_write_no_partial(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        offsets = {"/log": FileOffset(offset=50, inode=99)}
        _save_checkpoint(cp_file, offsets)
        assert cp_file.exists()
        content = cp_file.read_text()
        assert '"offset": 50' in content


class TestFileReader:
    def test_read_new_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"line1\nline2\nline3\n")
        lines, new_offset = _read_new_lines(f, 0)
        assert lines == [b"line1\n", b"line2\n", b"line3\n"]
        assert new_offset == 18

    def test_read_from_offset(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"line1\nline2\n")
        lines, _new_offset = _read_new_lines(f, 6)  # skip "line1\n"
        assert lines == [b"line2\n"]

    def test_read_no_new_content(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"line1\n")
        lines, _ = _read_new_lines(f, 6)
        assert lines == []

    def test_read_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"")
        lines, offset = _read_new_lines(f, 0)
        assert lines == []
        assert offset == 0


class TestRotation:
    def test_no_rotation(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"data\n")
        inode = f.stat().st_ino
        result = _check_rotation(f, FileOffset(offset=5, inode=inode))
        assert result == "ok"

    def test_inode_change(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"data\n")
        result = _check_rotation(f, FileOffset(offset=5, inode=99999))
        assert result == "rotated"

    def test_truncation(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"x")  # 1 byte
        inode = f.stat().st_ino
        result = _check_rotation(f, FileOffset(offset=100, inode=inode))
        assert result == "truncated"

    def test_deleted_file(self, tmp_path: Path) -> None:
        f = tmp_path / "gone.log"
        result = _check_rotation(f, FileOffset(offset=0, inode=1))
        assert result == "deleted"


class TestFileTailReceiver:
    def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        r = FileTailReceiver(mgr, source_id="test", file_paths=("/tmp/test.log",))
        assert isinstance(r, Receiver)

    async def test_start_stop_lifecycle(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"initial\n")
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="test",
            file_paths=(str(f),),
            checkpoint_dir=str(tmp_path),
        )
        await r.start()
        assert r.is_healthy()
        await r.stop()
        assert not r.is_healthy()

    async def test_tail_reads_new_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="tail",
            file_paths=(str(f),),
            checkpoint_dir=str(tmp_path),
            debounce_ms=200,
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            with f.open("ab") as fh:
                fh.write(b"hello world\n")
                fh.flush()
            raw = await asyncio.wait_for(mgr._queue.get(), timeout=5.0)
            assert raw.source_type == "file"
            assert b"hello world" in raw.data
        finally:
            await r.stop()

    async def test_glob_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.log").write_bytes(b"")
        (tmp_path / "b.log").write_bytes(b"")
        (tmp_path / "c.txt").write_bytes(b"")
        mgr = ReceiverManager()
        pattern = str(tmp_path / "*.log")
        r = FileTailReceiver(
            mgr,
            source_id="glob",
            file_paths=(pattern,),
            checkpoint_dir=str(tmp_path),
        )
        await r.start()
        try:
            assert len(r._watched_files) >= 2  # a.log, b.log
        finally:
            await r.stop()

    async def test_metadata_contains_path(self, tmp_path: Path) -> None:
        f = tmp_path / "meta.log"
        f.write_bytes(b"")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="meta",
            file_paths=(str(f),),
            checkpoint_dir=str(tmp_path),
            debounce_ms=200,
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            with f.open("ab") as fh:
                fh.write(b"test line\n")
                fh.flush()
            raw = await asyncio.wait_for(mgr._queue.get(), timeout=5.0)
            assert "path" in raw.metadata
            assert str(f) == raw.metadata["path"]
        finally:
            await r.stop()


class TestExports:
    def test_importable_from_package(self) -> None:
        from seerflow.receivers import FileTailReceiver as Exported
        from seerflow.receivers.file_tail import FileTailReceiver

        assert Exported is FileTailReceiver

    def test_in_all(self) -> None:
        import seerflow.receivers

        assert "FileTailReceiver" in seerflow.receivers.__all__
