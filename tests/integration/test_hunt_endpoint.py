"""Integration tests for ``POST /api/v1/hunt`` (S-072, FR-057).

Drives the FastAPI app through ``TestClient`` with a real ``SqliteBackend``
and a ``FakeLLMBackend`` so we never need the ``llama-cpp-python`` wheel
installed.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import LLMConfig
from seerflow.llm.hunt.cache import HuntCache
from seerflow.llm.hunt.service import NaturalLanguageHuntService
from seerflow.models.event import SeerflowEvent

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend

# Reuse the FakeLLMBackend from the explanation unit tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit" / "llm" / "explanation"))
from _fakes import FakeLLMBackend


def _make_event(idx: int = 0, *, now_ns: int | None = None) -> SeerflowEvent:
    """Events must fall inside the default 24h hunt window — anchor on now."""
    base = now_ns if now_ns is not None else time.time_ns()
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=base - 60_000_000_000 + idx,  # 1 minute ago + idx ns
        observed_ns=base - 60_000_000_000 + idx,
        message=f"ssh login from external host {idx}",
        source_type="auth",
    )


@pytest.fixture
def fake_backend() -> FakeLLMBackend:
    return FakeLLMBackend(response='{"text_query": "ssh"}')


@pytest.fixture
async def seeded_backend(backend: SqliteBackend) -> SqliteBackend:
    now_ns = time.time_ns()
    await backend.write_events([_make_event(0, now_ns=now_ns), _make_event(1, now_ns=now_ns)])
    await backend.flush()
    return backend


@pytest.fixture
def hunt_client(seeded_backend: SqliteBackend, fake_backend: FakeLLMBackend) -> TestClient:
    cache = HuntCache(max_entries=8, ttl_seconds=60)
    service = NaturalLanguageHuntService(
        backend=fake_backend,
        cache=cache,
        cfg=LLMConfig(hunt_max_results=50),
        log_store=seeded_backend,
    )
    app = create_api_app(
        log_store=seeded_backend,
        alert_store=seeded_backend,
        hunt_service=service,
        health_state={
            "pipeline": "running",
            "storage": "connected",
            "llm": "ready",
        },
    )
    return TestClient(app)


@pytest.fixture
def hunt_disabled_client(seeded_backend: SqliteBackend) -> TestClient:
    app = create_api_app(
        log_store=seeded_backend,
        alert_store=seeded_backend,
        hunt_service=None,
        health_state={
            "pipeline": "running",
            "storage": "connected",
            "llm": "disabled",
        },
    )
    return TestClient(app)


def test_hunt_returns_events_from_real_sqlite(
    hunt_client: TestClient, fake_backend: FakeLLMBackend
) -> None:
    resp = hunt_client.post("/api/v1/hunt", json={"query": "ssh logins"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "ssh logins"
    assert body["filters"] == {"text_query": "ssh"}
    # SQLite FTS index should match our seeded "ssh login from external host" events.
    assert body["total"] >= 1
    assert len(body["events"]) >= 1
    assert all("ssh" in e["message"] for e in body["events"])
    assert fake_backend.call_count == 1


def test_hunt_cache_hit_avoids_second_llm_call(
    hunt_client: TestClient, fake_backend: FakeLLMBackend
) -> None:
    hunt_client.post("/api/v1/hunt", json={"query": "ssh logins"})
    resp = hunt_client.post("/api/v1/hunt", json={"query": "ssh logins"})
    assert resp.status_code == 200
    assert resp.json()["cached"] is True
    # Backend only called once across the two requests.
    assert fake_backend.call_count == 1


def test_hunt_503_when_disabled(hunt_disabled_client: TestClient) -> None:
    resp = hunt_disabled_client.post("/api/v1/hunt", json={"query": "ssh"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["detail"] == "llm_not_ready"
    assert body["detail"]["status"] == "disabled"
