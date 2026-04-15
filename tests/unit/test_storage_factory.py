"""Tests for seerflow.storage.connect_storage factory (S-169)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.storage import connect_storage
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
class TestConnectStorage:
    async def test_sqlite_returns_sqlite_backend(self, tmp_path: Path) -> None:
        cfg = StorageConfig(backend="sqlite", data_dir=str(tmp_path))
        storage = await connect_storage(cfg)
        try:
            assert isinstance(storage, SqliteBackend)
        finally:
            await storage.close()

    async def test_postgresql_raises_not_implemented(self) -> None:
        cfg = StorageConfig(backend="postgresql")
        with pytest.raises(NotImplementedError, match="postgresql"):
            await connect_storage(cfg)

    async def test_unknown_backend_raises_value_error(self) -> None:
        cfg = StorageConfig(backend="redis")
        with pytest.raises(ValueError, match="redis"):
            await connect_storage(cfg)

    async def test_error_message_does_not_leak_credentials(self) -> None:
        cfg = StorageConfig(
            backend="postgresql", postgresql_url="postgres://secret@host/db"
        )
        with pytest.raises(NotImplementedError) as exc:
            await connect_storage(cfg)
        assert "secret" not in str(exc.value)
        assert "postgres://" not in str(exc.value)
