"""Tests for SqliteBackend — schema creation, event batch writes."""

from __future__ import annotations

import aiosqlite
import pytest

from seerflow.config import ConfigError
from seerflow.storage.sqlite import _init_schema, _validate_path


class TestPathValidation:
    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ConfigError, match="null byte"):
            _validate_path("/tmp/bad\x00path.db")

    def test_null_byte_in_middle(self) -> None:
        with pytest.raises(ConfigError, match="null byte"):
            _validate_path("/tmp/some\x00/dir/file.db")

    def test_valid_path_passes(self) -> None:
        _validate_path("/tmp/valid/path/seerflow.db")

    def test_empty_path_passes(self) -> None:
        _validate_path("")


class TestSchema:
    async def _init_memory_db(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(":memory:")
        await _init_schema(conn)
        return conn

    async def test_events_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_entity_events_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_events'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_alerts_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_model_state_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='model_state'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_fts5_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_events_indexes_exist(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_events_%'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
            assert indexes == {
                "idx_events_time",
                "idx_events_source_sev",
                "idx_events_template",
            }
        finally:
            await conn.close()

    async def test_alerts_indexes_exist(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_alerts_%'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
            assert indexes == {
                "idx_alerts_time",
                "idx_alerts_entity",
                "idx_alerts_dedup",
                "idx_alerts_type",
            }
        finally:
            await conn.close()

    async def test_fts_triggers_exist(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
            triggers = {row[0] for row in await cursor.fetchall()}
            assert triggers == {
                "events_fts_insert",
                "events_fts_delete",
                "events_fts_update",
            }
        finally:
            await conn.close()

    async def test_schema_idempotent(self) -> None:
        conn = await aiosqlite.connect(":memory:")
        try:
            await _init_schema(conn)
            await _init_schema(conn)
        finally:
            await conn.close()
