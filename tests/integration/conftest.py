"""Shared fixtures for integration tests.

Consolidates the duplicate ``backend`` fixture that previously appeared,
identical, in eight test files. See docs/stories/S-188.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    """Function-scoped SqliteBackend on a fresh per-test SQLite DB."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()
