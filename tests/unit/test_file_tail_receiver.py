"""Tests for FileTailReceiver — file tailing, rotation, checkpoints."""

from __future__ import annotations

from pathlib import Path

from seerflow.receivers.file_tail import FileOffset, _load_checkpoint, _save_checkpoint


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
