"""Tests for the FastAPI entity search endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.entities import router
from seerflow.models.event import SeerflowEvent


def _make_app(
    log_store: AsyncMock,
    entity_store: AsyncMock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.storage = StorageDeps(
        log_store=log_store,
        alert_store=AsyncMock(),
        entity_store=entity_store,
    )
    app.include_router(router, prefix="/api/v1")
    return app


class TestEntitySearch:
    """Tests for GET /api/v1/entities/search."""

    def test_fallback_extracts_entities_from_events(self) -> None:
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_ips=("10.0.0.1",),
            related_users=("admin",),
        )
        log_store = AsyncMock()
        log_store.search_text.return_value = [event]
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=admin")
        assert resp.status_code == 200
        results = resp.json()
        types = {r["entity_type"] for r in results}
        values = {r["entity_value"] for r in results}
        assert "ip" in types
        assert "user" in types
        assert "10.0.0.1" in values
        assert "admin" in values

    def test_no_results(self) -> None:
        log_store = AsyncMock()
        log_store.search_text.return_value = []
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=unknown")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_missing_q_returns_422(self) -> None:
        log_store = AsyncMock()
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search")
        assert resp.status_code == 422

    def test_deduplicates_entities(self) -> None:
        event1 = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_ips=("10.0.0.1",),
        )
        event2 = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1,
            observed_ns=1,
            related_ips=("10.0.0.1",),
        )
        log_store = AsyncMock()
        log_store.search_text.return_value = [event1, event2]
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=10.0.0.1")
        assert resp.status_code == 200
        results = resp.json()
        ip_results = [r for r in results if r["entity_value"] == "10.0.0.1"]
        assert len(ip_results) == 1
