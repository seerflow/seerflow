"""Tests for GET /api/v1/anomaly/timeline route."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.anomaly_timeline import (
    BUCKET_NS,
    AnomalyTimelineRing,
)
from seerflow.api.deps import StorageDeps
from seerflow.api.routes import anomaly


def _app(ring: AnomalyTimelineRing, alert_store: MagicMock) -> FastAPI:
    app = FastAPI()
    app.state.anomaly_timeline_ring = ring
    app.state.storage = StorageDeps(
        log_store=MagicMock(),
        alert_store=alert_store,
        entity_store=None,
    )
    app.include_router(anomaly.router, prefix="/api/v1")
    return app


@pytest.mark.unit
class TestAnomalyRoute:
    def test_happy_path_returns_items_and_meta(self) -> None:
        ring = AnomalyTimelineRing()
        # Anchor the recorded event near wall-clock now so the 1h window
        # covers it (the route uses time.time_ns() internally).
        now_bucket = (time.time_ns() // BUCKET_NS) * BUCKET_NS
        ring.record_score(now_bucket - BUCKET_NS, 0.5, 0.9, "syslog")
        alert_store = MagicMock()
        alert_store.query_alerts = AsyncMock(return_value=MagicMock(items=[]))
        with TestClient(_app(ring, alert_store)) as client:
            r = client.get("/api/v1/anomaly/timeline?range=1h&resolution=1m")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"] == {"range": "1h", "resolution": "1m", "source": None}
        assert isinstance(body["items"], list)
        assert len(body["items"]) == 60

    def test_invalid_range_returns_422(self) -> None:
        ring = AnomalyTimelineRing()
        alert_store = MagicMock()
        alert_store.query_alerts = AsyncMock(return_value=MagicMock(items=[]))
        with TestClient(_app(ring, alert_store)) as client:
            r = client.get("/api/v1/anomaly/timeline?range=bogus")
        assert r.status_code == 422

    def test_invalid_resolution_for_range_returns_422(self) -> None:
        ring = AnomalyTimelineRing()
        alert_store = MagicMock()
        alert_store.query_alerts = AsyncMock(return_value=MagicMock(items=[]))
        with TestClient(_app(ring, alert_store)) as client:
            r = client.get("/api/v1/anomaly/timeline?range=7d&resolution=1m")
        assert r.status_code == 422
        assert "resolution" in r.json()["detail"].lower()

    def test_invalid_source_regex_returns_422(self) -> None:
        ring = AnomalyTimelineRing()
        alert_store = MagicMock()
        alert_store.query_alerts = AsyncMock(return_value=MagicMock(items=[]))
        with TestClient(_app(ring, alert_store)) as client:
            r = client.get("/api/v1/anomaly/timeline?range=1h&source=with space")
        assert r.status_code == 422

    def test_alert_count_joined_from_alert_store(self) -> None:
        ring = AnomalyTimelineRing()
        now_bucket = (time.time_ns() // BUCKET_NS) * BUCKET_NS
        ts = now_bucket - BUCKET_NS
        ring.record_score(ts, 0.5, 0.9, "syslog")
        alert = MagicMock()
        alert.timestamp_ns = ts + 1000
        alert_store = MagicMock()
        alert_store.query_alerts = AsyncMock(return_value=MagicMock(items=[alert]))
        with TestClient(_app(ring, alert_store)) as client:
            r = client.get("/api/v1/anomaly/timeline?range=1h&resolution=1m")
        items = r.json()["items"]
        target = next(b for b in items if b["bucket_start_ns"] == ts)
        assert target["alert_count"] == 1
