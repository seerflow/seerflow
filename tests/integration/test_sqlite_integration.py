"""Integration tests for SqliteBackend with real files."""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow.config import ConfigError, StorageConfig
from seerflow.storage.protocols import LogStore
from seerflow.storage.sqlite import SqliteBackend


class TestSqliteIntegration:
    async def test_directory_auto_created(self, tmp_path: Path) -> None:
        subdir = tmp_path / "deep" / "nested" / "dir"
        db_path = str(subdir / "seerflow.db")
        config = StorageConfig(backend="sqlite", sqlite_path=db_path)
        backend = await SqliteBackend.connect(config)
        try:
            assert subdir.exists()
            assert Path(db_path).exists()
        finally:
            await backend.close()

    async def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "seerflow.db")
        config = StorageConfig(backend="sqlite", sqlite_path=db_path)
        backend = await SqliteBackend.connect(config)
        try:
            cursor = await backend._conn.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row[0] == "wal"
        finally:
            await backend.close()

    async def test_null_byte_path_rejected(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path="/tmp/bad\x00path.db")
        with pytest.raises(ConfigError, match="null byte"):
            await SqliteBackend.connect(config)

    async def test_isinstance_log_store(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "seerflow.db")
        config = StorageConfig(backend="sqlite", sqlite_path=db_path)
        backend = await SqliteBackend.connect(config)
        try:
            assert isinstance(backend, LogStore)
        finally:
            await backend.close()

    async def test_db_file_persists_after_close(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "seerflow.db")
        config = StorageConfig(backend="sqlite", sqlite_path=db_path)
        backend = await SqliteBackend.connect(config)
        await backend.close()
        assert Path(db_path).exists()
