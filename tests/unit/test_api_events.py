"""Tests for the FastAPI events endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.events import router
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import Page


def _make_event(**overrides) -> SeerflowEvent:
    defaults = {
        "event_id": uuid.uuid4(),
        "timestamp_ns": 1_000_000_000,
        "observed_ns": 1_000_000_001,
        "message": "test log",
        "source_type": "syslog",
    }
    defaults.update(overrides)
    return SeerflowEvent(**defaults)


def _make_app(log_store: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.state.storage = StorageDeps(
        log_store=log_store,
        alert_store=AsyncMock(),
    )
    app.include_router(router, prefix="/api/v1")
    return app


class TestListEvents:
    """Tests for GET /api/v1/events."""

    def test_default_params_returns_paginated(self) -> None:
        event = _make_event()
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(event,),
            total=1,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["event_id"] == str(event.event_id)

    def test_pagination_params(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(),
            total=100,
            page=3,
            limit=10,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events?page=3&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 3
        assert body["limit"] == 10

    def test_since_until_filtering(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events?since=2026-04-09T00:00:00&until=2026-04-09T23:59:59")
        assert resp.status_code == 200
        call_args = log_store.query_events.call_args[0][0]
        assert call_args.time_range is not None
        assert call_args.time_range.start_ns < call_args.time_range.end_ns

    def test_since_after_until_returns_400(self) -> None:
        log_store = AsyncMock()
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events?since=2026-04-10T00:00:00&until=2026-04-09T00:00:00")
        assert resp.status_code == 400

    def test_invalid_timestamp_returns_422(self) -> None:
        log_store = AsyncMock()
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events?since=garbage")
        assert resp.status_code == 422

    def test_source_filter(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events?source=syslog")
        assert resp.status_code == 200
        call_args = log_store.query_events.call_args[0][0]
        assert call_args.source_type == "syslog"

    def test_empty_results(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["total"] == 0

    def test_limit_capped_at_1000(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=1000,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/events?limit=5000")
        assert resp.status_code == 200
        call_args = log_store.query_events.call_args[0][0]
        assert call_args.limit == 1000
