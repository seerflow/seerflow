"""Integration tests for ``seerflow templates prune|reset`` (S-077).

Drives a real SQLite-backed storage layer end-to-end: writes templates
via the production write API, then runs ``run_templates`` and verifies
that the persisted ``templates`` and ``model_state`` rows actually
disappear from disk (round-trip via a fresh backend connection).
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

import pytest

from seerflow import templates_cmd
from seerflow.config import StorageConfig
from seerflow.storage.sqlite import SqliteBackend, TemplateInfo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class _NoCloseProxy:
    """Forwards everything to the underlying backend except ``close``."""

    def __init__(self, inner: SqliteBackend) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def close(self) -> None:
        return None


@pytest.fixture
async def db_path(tmp_path: Path) -> AsyncIterator[Path]:
    yield tmp_path / "templates_cli_integration.db"


def _seed_templates(counts: tuple[int, ...]) -> list[TemplateInfo]:
    return [
        TemplateInfo(
            template_id=i,
            template_str=f"tmpl-{i}",
            first_seen_ns=1_700_000_000_000_000_000 + i,
            last_seen_ns=1_700_000_000_000_000_000 + i * 2,
            event_count=c,
            example_message=f"raw {i}",
        )
        for i, c in enumerate(counts, start=1)
    ]


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "command": "templates",
        "templates_cmd": "list",
        "limit": 100,
        "json": False,
        "min_count": None,
        "yes": True,
        "config": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.mark.integration
async def test_prune_persists_to_disk(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`prune` removes rows from the on-disk templates table."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(db_path))

    backend = await SqliteBackend.connect(config)
    try:
        await backend.write_templates(_seed_templates((1, 2, 3, 5)))
    finally:
        await backend.close()

    backend = await SqliteBackend.connect(config)
    try:

        async def _conn(_args: argparse.Namespace) -> object:
            return _NoCloseProxy(backend)

        monkeypatch.setattr(templates_cmd, "_connect_storage_from_args", _conn)
        rc = await templates_cmd.run_templates(
            _args(templates_cmd="prune", min_count=3, yes=True, json=True)
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload == {"deleted": 2, "remaining": 2}
    finally:
        await backend.close()

    # Reconnect from scratch — confirms disk persistence
    fresh = await SqliteBackend.connect(config)
    try:
        rows = await fresh.get_templates()
        assert sorted(t.event_count for t in rows) == [3, 5]
    finally:
        await fresh.close()


@pytest.mark.integration
async def test_reset_persists_to_disk(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`reset` wipes both the templates table and the drain3:global state."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(db_path))

    backend = await SqliteBackend.connect(config)
    try:
        await backend.write_templates(_seed_templates((10, 20, 30)))
        await backend.save_state("drain3:global", b"persisted-blob")
    finally:
        await backend.close()

    backend = await SqliteBackend.connect(config)
    try:

        async def _conn(_args: argparse.Namespace) -> object:
            return _NoCloseProxy(backend)

        monkeypatch.setattr(templates_cmd, "_connect_storage_from_args", _conn)
        rc = await templates_cmd.run_templates(_args(templates_cmd="reset", yes=True, json=True))
        assert rc == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload == {"deleted_templates": 3, "drain_state_cleared": True}
    finally:
        await backend.close()

    fresh = await SqliteBackend.connect(config)
    try:
        assert await fresh.get_templates() == []
        assert await fresh.load_state("drain3:global") is None
    finally:
        await fresh.close()


@pytest.mark.integration
async def test_list_reads_from_disk(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`list` reads what was written and respects --json."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(db_path))

    backend = await SqliteBackend.connect(config)
    try:
        await backend.write_templates(_seed_templates((1, 5)))
    finally:
        await backend.close()

    backend = await SqliteBackend.connect(config)
    try:

        async def _conn(_args: argparse.Namespace) -> object:
            return _NoCloseProxy(backend)

        monkeypatch.setattr(templates_cmd, "_connect_storage_from_args", _conn)
        rc = await templates_cmd.run_templates(_args(templates_cmd="list", json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out.strip())
        assert {item["template_id"] for item in data} == {1, 2}
        assert {item["event_count"] for item in data} == {1, 5}
    finally:
        await backend.close()
