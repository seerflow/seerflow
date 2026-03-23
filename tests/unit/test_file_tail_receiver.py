"""Tests for FileTailReceiver — file tailing, rotation, checkpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from seerflow.config import ReceiverConfig, load_config
from seerflow.receivers.base import Receiver
from seerflow.receivers.file_tail import (
    FileOffset,
    FileTailReceiver,
    _check_rotation,
    _is_path_allowed,
    _load_checkpoint,
    _read_new_lines,
    _save_checkpoint,
    _validate_pattern,
)
from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from pathlib import Path


class TestLineSizeLimit:
    def test_normal_lines_pass(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"short line\n")
        lines, offset = _read_new_lines(f, 0)
        assert len(lines) == 1
        assert lines[0] == b"short line\n"

    def test_oversized_line_discarded(self, tmp_path: Path) -> None:
        from seerflow.receivers.file_tail import _MAX_LINE_BYTES

        f = tmp_path / "test.log"
        oversized = b"x" * (_MAX_LINE_BYTES + 1) + b"\n"
        f.write_bytes(b"good\n" + oversized + b"also good\n")
        lines, offset = _read_new_lines(f, 0)
        assert b"good\n" in lines
        assert oversized not in lines
        # "also good\n" may not appear because _MAX_BYTES_PER_READ (64 KB)
        # limits how much readlines reads per call; the oversized line alone
        # exceeds that budget so the trailing line is deferred to a later read.
        # Verify it is retrievable with a second read from the new offset:
        lines2, _ = _read_new_lines(f, offset)
        assert b"also good\n" in lines2

    def test_exactly_max_size_passes(self, tmp_path: Path) -> None:
        from seerflow.receivers.file_tail import _MAX_LINE_BYTES

        f = tmp_path / "test.log"
        exact = b"x" * (_MAX_LINE_BYTES - 1) + b"\n"
        f.write_bytes(exact)
        lines, offset = _read_new_lines(f, 0)
        assert len(lines) == 1


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

    def test_load_corrupted_returns_empty(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        cp_file.write_text("not valid json {{{")
        loaded = _load_checkpoint(cp_file)
        assert loaded == {}

    def test_load_not_dict_returns_empty(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        cp_file.write_text('"just a string"')
        loaded = _load_checkpoint(cp_file)
        assert loaded == {}

    def test_load_negative_offset_skipped(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        cp_file.write_text('{"bad": {"offset": -1, "inode": 1}}')
        loaded = _load_checkpoint(cp_file)
        assert loaded == {}

    def test_load_invalid_types_skipped(self, tmp_path: Path) -> None:
        cp_file = tmp_path / "offsets.json"
        data = '{"ok": {"offset": 10, "inode": 1}, "bad": {"offset": "x", "inode": 1}}'
        cp_file.write_text(data)
        loaded = _load_checkpoint(cp_file)
        assert len(loaded) == 1
        assert "ok" in loaded


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

    def test_partial_line_not_emitted(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"complete\npartial")  # no trailing newline
        lines, new_offset = _read_new_lines(f, 0)
        assert lines == [b"complete\n"]
        assert new_offset == 9  # only complete line consumed

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
        st = f.stat()
        result = _check_rotation(st, FileOffset(offset=5, inode=st.st_ino))
        assert result == "ok"

    def test_inode_change(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"data\n")
        st = f.stat()
        result = _check_rotation(st, FileOffset(offset=5, inode=99999))
        assert result == "rotated"

    def test_truncation(self, tmp_path: Path) -> None:
        f = tmp_path / "test.log"
        f.write_bytes(b"x")  # 1 byte
        st = f.stat()
        result = _check_rotation(st, FileOffset(offset=100, inode=st.st_ino))
        assert result == "truncated"

    def test_deleted_file(self) -> None:
        result = _check_rotation(None, FileOffset(offset=0, inode=1))
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


class TestFileTailEdgeCases:
    async def test_start_idempotent(self, tmp_path: Path) -> None:
        """Calling start() twice does nothing on second call."""
        f = tmp_path / "test.log"
        f.write_bytes(b"")
        mgr = ReceiverManager()
        r = FileTailReceiver(mgr, source_id="t", file_paths=(str(f),))
        await r.start()
        await r.start()  # second call is no-op
        assert r.is_healthy()
        await r.stop()

    async def test_start_no_matching_files(self, tmp_path: Path) -> None:
        """Start with glob that matches nothing — still healthy, no crash."""
        mgr = ReceiverManager()
        r = FileTailReceiver(mgr, source_id="t", file_paths=(str(tmp_path / "*.nonexistent"),))
        await r.start()
        assert r.is_healthy()
        assert len(r._watched_files) == 0
        # _watch_loop with no dirs sets ready immediately and returns
        await r.wait_ready()
        await r.stop()

    async def test_stop_without_checkpoint_dir(self, tmp_path: Path) -> None:
        """Stop without checkpoint_dir does not crash."""
        f = tmp_path / "test.log"
        f.write_bytes(b"")
        mgr = ReceiverManager()
        r = FileTailReceiver(mgr, source_id="t", file_paths=(str(f),))
        await r.start()
        await r.stop()  # no checkpoint_dir — should not crash
        assert not r.is_healthy()

    async def test_checkpoint_persisted_on_stop(self, tmp_path: Path) -> None:
        """Checkpoint file is written on stop when checkpoint_dir is set."""
        f = tmp_path / "test.log"
        f.write_bytes(b"data\n")
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="t",
            file_paths=(str(f),),
            checkpoint_dir=str(tmp_path),
        )
        await r.start()
        await r.stop()
        cp = tmp_path / "file_offsets.json"
        assert cp.exists()

    async def test_process_deleted_file(self, tmp_path: Path) -> None:
        """Calling _process_file on a deleted file logs warning and removes it."""
        f = tmp_path / "gone.log"
        f.write_bytes(b"data\n")
        mgr = ReceiverManager()
        r = FileTailReceiver(mgr, source_id="t", file_paths=(str(f),))
        await r.start()
        path_str = str(f.resolve())
        assert path_str in r._watched_files
        f.unlink()
        await r._process_file(path_str)
        assert path_str not in r._watched_files
        await r.stop()

    async def test_process_truncated_file(self, tmp_path: Path) -> None:
        """Truncated file resets offset to 0 and reads from start."""
        f = tmp_path / "trunc.log"
        f.write_bytes(b"old data line\n")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(mgr, source_id="t", file_paths=(str(f),))
        await r.start()
        path_str = str(f.resolve())
        # Simulate: offset is beyond file size (truncation)
        inode = f.stat().st_ino
        r._offsets[path_str] = FileOffset(offset=9999, inode=inode)
        # Write new content after truncation
        f.write_bytes(b"new line\n")
        await r._process_file(path_str)
        assert r._offsets[path_str].offset == 9  # "new line\n" = 9 bytes
        raw = await asyncio.wait_for(mgr._queue.get(), timeout=2.0)
        assert b"new line" in raw.data
        await r.stop()


class TestExports:
    def test_importable_from_package(self) -> None:
        from seerflow.receivers import FileTailReceiver as Exported
        from seerflow.receivers.file_tail import FileTailReceiver

        assert Exported is FileTailReceiver

    def test_in_all(self) -> None:
        import seerflow.receivers

        assert "FileTailReceiver" in seerflow.receivers.__all__


class TestIsPathAllowed:
    """Direct unit tests for _is_path_allowed — security boundary function."""

    def test_empty_roots_allows_all(self) -> None:
        """Empty allowed_roots tuple means no restriction — always True."""
        assert _is_path_allowed("/any/path/file.log", ()) is True

    def test_path_under_root_allowed(self, tmp_path: Path) -> None:
        """Path under an allowed root returns True."""
        root = str(tmp_path)
        child = str(tmp_path / "subdir" / "file.log")
        assert _is_path_allowed(child, (root,)) is True

    def test_path_outside_root_rejected(self, tmp_path: Path) -> None:
        """Path outside all allowed roots returns False."""
        allowed = str(tmp_path / "allowed")
        outside = str(tmp_path / "outside" / "file.log")
        assert _is_path_allowed(outside, (allowed,)) is False

    def test_root_prefix_not_confused_with_directory(self, tmp_path: Path) -> None:
        """/var/log must NOT match /var/log_archive/file.log."""
        root = str(tmp_path / "var" / "log")
        (tmp_path / "var" / "log").mkdir(parents=True, exist_ok=True)
        (tmp_path / "var" / "log_archive").mkdir(parents=True, exist_ok=True)
        file_path = str(tmp_path / "var" / "log_archive" / "file.log")
        assert _is_path_allowed(file_path, (root,)) is False

    def test_multiple_roots_any_match(self, tmp_path: Path) -> None:
        """File under second root is allowed when first root doesn't match."""
        root_a = str(tmp_path / "a")
        root_b = str(tmp_path / "b")
        (tmp_path / "b" / "sub").mkdir(parents=True, exist_ok=True)
        file_path = str(tmp_path / "b" / "sub" / "file.log")
        assert _is_path_allowed(file_path, (root_a, root_b)) is True


class TestPathConfinement:
    """S-117: path confinement — reject .. and enforce allowed_log_roots."""

    def test_reject_dotdot_pattern(self) -> None:
        """Pattern containing '..' component raises ValueError."""
        with pytest.raises(ValueError, match=r"\.\.|parent traversal"):
            _validate_pattern("/var/log/../etc/shadow")
        with pytest.raises(ValueError, match=r"\.\.|parent traversal"):
            _validate_pattern("../relative/path")
        # Clean patterns must NOT raise
        _validate_pattern("/var/log/syslog")
        _validate_pattern("/var/log/*.log")

    async def test_reject_path_outside_allowed_roots(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Resolved path not under any allowed root is skipped with warning."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_log = outside_dir / "sneaky.log"
        outside_log.write_bytes(b"data\n")
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="confined",
            file_paths=(str(outside_log),),
            allowed_log_roots=(str(allowed_dir),),
        )
        with caplog.at_level(logging.WARNING):
            await r.start()
        # File outside allowed root must NOT be watched
        assert len(r._watched_files) == 0
        assert "not under any allowed log root" in caplog.text
        await r.stop()

    async def test_allowed_roots_empty_allows_all(self, tmp_path: Path) -> None:
        """Empty allowed_log_roots means no restriction — all files accepted."""
        f = tmp_path / "any.log"
        f.write_bytes(b"data\n")
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="open",
            file_paths=(str(f),),
            allowed_log_roots=(),  # empty = no restriction
        )
        await r.start()
        assert len(r._watched_files) == 1
        await r.stop()

    def test_config_allowed_log_roots(self, tmp_path: Path) -> None:
        """ReceiverConfig has allowed_log_roots field and YAML loads it."""
        # Default is empty tuple
        cfg = ReceiverConfig()
        assert cfg.allowed_log_roots == ()

        # YAML round-trip
        yaml_content = "receivers:\n  allowed_log_roots:\n    - /var/log\n    - /opt/logs\n"
        config_file = tmp_path / "seerflow.yaml"
        config_file.write_text(yaml_content)
        loaded = load_config(str(config_file))
        assert loaded.receivers.allowed_log_roots == ("/var/log", "/opt/logs")


class TestCheckpointDirValidation:
    """S-117: checkpoint_dir must not contain '..' components."""

    def test_checkpoint_dir_rejects_dotdot(self) -> None:
        """checkpoint_dir with '..' raises ValueError."""
        mgr = ReceiverManager()
        with pytest.raises(ValueError, match=r"checkpoint_dir must not contain '\.\.'"):
            FileTailReceiver(
                mgr,
                source_id="test",
                file_paths=("/tmp/test.log",),
                checkpoint_dir="/var/data/../etc",
            )

    def test_checkpoint_dir_clean_path_accepted(self, tmp_path: Path) -> None:
        """Normal checkpoint_dir without '..' works fine."""
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="test",
            file_paths=("/tmp/test.log",),
            checkpoint_dir=str(tmp_path / "checkpoints"),
        )
        assert r._checkpoint_path is not None


class TestSymlinkProtection:
    """S-117: symlink protection — skip symlinks during glob expansion."""

    async def test_symlink_skipped_during_glob(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Symlink in glob results is skipped with a warning log."""
        real_file = tmp_path / "real.log"
        real_file.write_bytes(b"data\n")
        symlink_file = tmp_path / "link.log"
        symlink_file.symlink_to(real_file)
        pattern = str(tmp_path / "*.log")
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="symtest",
            file_paths=(pattern,),
        )
        with caplog.at_level(logging.WARNING):
            await r.start()
        # Only the real file should be watched, not the symlink
        resolved_real = str(real_file.resolve())
        assert resolved_real in r._watched_files
        # The symlink target resolves to the same path, but the symlink
        # itself must have been skipped — so only 1 watched file
        assert len(r._watched_files) == 1
        assert "symlink" in caplog.text.lower()
        await r.stop()

    async def test_regular_file_not_skipped(self, tmp_path: Path) -> None:
        """Normal (non-symlink) file passes through glob expansion."""
        f = tmp_path / "normal.log"
        f.write_bytes(b"data\n")
        pattern = str(tmp_path / "*.log")
        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="regular",
            file_paths=(pattern,),
        )
        await r.start()
        assert len(r._watched_files) == 1
        assert str(f.resolve()) in r._watched_files
        await r.stop()


class TestLiteralReturnType:
    """Task 4: _check_rotation must return one of the four Literal values."""

    def test_check_rotation_return_type(self, tmp_path: Path) -> None:
        """Return value is always one of the four allowed Literal strings."""
        valid_values = {"ok", "rotated", "truncated", "deleted"}

        # "ok" case
        f = tmp_path / "test.log"
        f.write_bytes(b"data\n")
        st = f.stat()
        assert _check_rotation(st, FileOffset(offset=5, inode=st.st_ino)) in valid_values

        # "rotated" case
        assert _check_rotation(st, FileOffset(offset=5, inode=99999)) in valid_values

        # "truncated" case
        assert _check_rotation(st, FileOffset(offset=9999, inode=st.st_ino)) in valid_values

        # "deleted" case
        assert _check_rotation(None, FileOffset(offset=0, inode=1)) in valid_values

    def test_no_encoding_param(self) -> None:
        """FileTailReceiver.__init__ must not accept an 'encoding' parameter."""
        import inspect

        sig = inspect.signature(FileTailReceiver.__init__)
        assert "encoding" not in sig.parameters, (
            "FileTailReceiver.__init__ should not have an 'encoding' parameter"
        )


class TestReGlobOnNewFiles:
    """S-117: re-glob on new file events — discover files created after start."""

    async def test_new_file_discovered_after_start(self, tmp_path: Path) -> None:
        """Create a new file matching the glob after start → it gets picked up."""
        existing = tmp_path / "app.log"
        existing.write_bytes(b"initial\n")
        pattern = str(tmp_path / "*.log")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="reglob",
            file_paths=(pattern,),
            debounce_ms=200,
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            # Create a NEW file matching the glob after start
            new_file = tmp_path / "new_app.log"
            new_file.write_bytes(b"new content\n")
            # Wait for the watcher to pick it up via re-glob
            deadline = asyncio.get_running_loop().time() + 5.0
            resolved_new = str(new_file.resolve())
            while asyncio.get_running_loop().time() < deadline:
                if resolved_new in r._watched_files:
                    break
                await asyncio.sleep(0.2)
            assert resolved_new in r._watched_files, (
                f"New file {resolved_new} not discovered via re-glob"
            )
        finally:
            await r.stop()

    async def test_non_matching_new_file_ignored(self, tmp_path: Path) -> None:
        """New file NOT matching the glob pattern is ignored by re-glob."""
        existing = tmp_path / "app.log"
        existing.write_bytes(b"initial\n")
        pattern = str(tmp_path / "*.log")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="reglob",
            file_paths=(pattern,),
            debounce_ms=200,
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            # Create a file that does NOT match the *.log pattern
            non_matching = tmp_path / "data.txt"
            non_matching.write_bytes(b"should be ignored\n")
            # Give watcher time to process the event
            await asyncio.sleep(1.0)
            resolved_nm = str(non_matching.resolve())
            assert resolved_nm not in r._watched_files, (
                f"Non-matching file {resolved_nm} should NOT be in watched_files"
            )
        finally:
            await r.stop()

    async def test_re_glob_respects_allowed_roots(self, tmp_path: Path) -> None:
        """New file outside allowed_log_roots is NOT added via re-glob."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        # Existing file inside allowed dir
        existing = allowed_dir / "app.log"
        existing.write_bytes(b"initial\n")
        # Glob pattern covers both dirs (use ** recursive or multiple patterns)
        pattern_allowed = str(allowed_dir / "*.log")
        pattern_outside = str(outside_dir / "*.log")
        mgr = ReceiverManager(queue_maxsize=100)
        r = FileTailReceiver(
            mgr,
            source_id="reglob",
            file_paths=(pattern_allowed, pattern_outside),
            debounce_ms=200,
            allowed_log_roots=(str(allowed_dir),),
        )
        await r.start()
        await r.wait_ready()
        try:
            await asyncio.sleep(0.1)
            # Create new file outside allowed roots
            outside_file = outside_dir / "sneaky.log"
            outside_file.write_bytes(b"sneaky data\n")
            # Also create a new file inside allowed roots
            new_allowed = allowed_dir / "new_app.log"
            new_allowed.write_bytes(b"allowed data\n")
            # Wait for re-glob to pick up the allowed file
            deadline = asyncio.get_running_loop().time() + 5.0
            resolved_allowed = str(new_allowed.resolve())
            while asyncio.get_running_loop().time() < deadline:
                if resolved_allowed in r._watched_files:
                    break
                await asyncio.sleep(0.2)
            assert resolved_allowed in r._watched_files, (
                "New file under allowed root should be discovered"
            )
            resolved_outside = str(outside_file.resolve())
            assert resolved_outside not in r._watched_files, (
                "File outside allowed roots must NOT be added via re-glob"
            )
        finally:
            await r.stop()


class TestCheckpointKeyFiltering:
    """S-117: checkpoint keys must be filtered by allowed_log_roots on load."""

    async def test_checkpoint_keys_filtered_by_allowed_roots(
        self,
        tmp_path: Path,
    ) -> None:
        """Keys in checkpoint outside allowed roots are dropped on start()."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        # Create a real file inside allowed dir so glob has something to match
        allowed_log = allowed_dir / "app.log"
        allowed_log.write_bytes(b"data\n")
        allowed_resolved = str(allowed_log.resolve())
        outside_resolved = str((outside_dir / "evil.log").resolve())

        # Write a checkpoint with both an allowed and an outside path
        cp_file = tmp_path / "file_offsets.json"
        import json

        cp_data = {
            allowed_resolved: {"offset": 10, "inode": 1},
            outside_resolved: {"offset": 20, "inode": 2},
        }
        cp_file.write_text(json.dumps(cp_data))

        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="ckpt-filter",
            file_paths=(str(allowed_log),),
            checkpoint_dir=str(tmp_path),
            allowed_log_roots=(str(allowed_dir),),
        )
        await r.start()
        # The outside path must have been filtered out of _offsets
        assert allowed_resolved in r._offsets
        assert outside_resolved not in r._offsets
        await r.stop()


class TestAllowedRootsResolvedAtInit:
    """S-117: allowed_log_roots should be resolved once at __init__."""

    def test_allowed_roots_resolved_at_init(self, tmp_path: Path) -> None:
        """Symlink roots are resolved eagerly — stored value is the real path."""
        real_dir = tmp_path / "real_logs"
        real_dir.mkdir()
        link_dir = tmp_path / "link_logs"
        link_dir.symlink_to(real_dir)

        mgr = ReceiverManager()
        r = FileTailReceiver(
            mgr,
            source_id="resolve-test",
            file_paths=("/tmp/test.log",),
            allowed_log_roots=(str(link_dir),),
        )
        # The stored root should be the resolved (real) path, not the symlink
        assert len(r._allowed_log_roots) == 1
        assert r._allowed_log_roots[0] == str(real_dir.resolve())
        assert str(link_dir) != r._allowed_log_roots[0]
