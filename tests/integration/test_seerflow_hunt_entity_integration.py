"""Integration test for ``seerflow hunt`` entity routing (S-076).

Drives a real SQLite-backed storage layer, writes events for two distinct
IPs, then runs ``run_hunt`` end-to-end against the live backend. The
entity-detection module routes the IP query to a structured EventQuery
without invoking the LLM service.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow import hunt_cmd
from seerflow.config import StorageConfig
from seerflow.models.entity import generate_ip_id
from seerflow.models.event import SeerflowEvent
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class _NoCloseProxy:
    """See the export integration test for rationale."""

    def __init__(self, inner: SqliteBackend) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def close(self) -> None:
        return None


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    config = StorageConfig(
        backend="sqlite",
        sqlite_path=str(tmp_path / "hunt_entity_integration.db"),
    )
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()


def _event_for_ip(ip: str, idx: int, *, ts_ns: int) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=ts_ns + idx,
        observed_ns=ts_ns + idx,
        message=f"connection from {ip}",
        source_type="auth",
        entity_refs=(str(generate_ip_id(ip)),),
    )


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "command": "hunt",
        "query": "10.0.0.7",
        "limit": None,
        "db": None,
        "json": True,
        "config": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.mark.integration
async def test_hunt_entity_ip_routes_to_storage(
    backend: SqliteBackend,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: 5 events for 10.0.0.7 + 5 for 10.0.0.8 → hunt by IP returns 5."""
    now_ns = time.time_ns()
    events_7 = [_event_for_ip("10.0.0.7", i, ts_ns=now_ns - 60_000_000_000) for i in range(5)]
    events_8 = [_event_for_ip("10.0.0.8", i, ts_ns=now_ns - 60_000_000_000) for i in range(5)]
    await backend.write_events([*events_7, *events_8])
    await backend.flush()

    async def fake_build(_args: argparse.Namespace) -> tuple[None, object]:
        return None, _NoCloseProxy(backend)

    monkeypatch.setattr(hunt_cmd, "_build_service_and_storage", fake_build)

    rc = await hunt_cmd.run_hunt(_args(query="10.0.0.7"))
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["total"] == 5
    assert payload["filters"]["mode"] == "entity"
    assert payload["filters"]["entity_type"] == "ip"
    assert payload["filters"]["entity_value"] == "10.0.0.7"
    assert payload["filters"]["entity_uuid"] == str(generate_ip_id("10.0.0.7"))
    assert payload["model"] == "entity"
