"""Tests for the risk-history bucket helper and endpoint (S-060.F1)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.entities import _bucket_alerts, router
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.models.query import Page


def _alert(ts_ns: int, risk: float, rule: str, entity: str) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.ERROR,
        rule_name=rule,
        description="test",
        entity_uuid=entity,
        entity_value="e",
        entity_type="user",
        contributing_events=(uuid.uuid4(),),
        risk_score=risk,
        dedup_key="",
    )


class TestBucketAlerts:
    def test_empty_input_zero_fills_range(self) -> None:
        res_ns = 60_000_000_000
        range_ns = 3_600_000_000_000
        now_ns = range_ns
        items = _bucket_alerts([], now_ns=now_ns, range_ns=range_ns, res_ns=res_ns)
        assert len(items) == 60
        assert all(b.points == 0.0 for b in items)
        assert all(b.alert_count == 0 for b in items)
        assert all(b.top_rule_name == "" for b in items)
        assert items[0].bucket_start_ns == 0
        assert items[-1].bucket_start_ns == 59 * res_ns

    def test_sum_points_in_bucket(self) -> None:
        res_ns = 60_000_000_000
        range_ns = 3_600_000_000_000
        now_ns = range_ns
        alerts = [
            _alert(10 * res_ns + 100, 0.3, "rule_a", "e"),
            _alert(10 * res_ns + 200, 0.7, "rule_b", "e"),
        ]
        items = _bucket_alerts(alerts, now_ns=now_ns, range_ns=range_ns, res_ns=res_ns)
        target = next(b for b in items if b.bucket_start_ns == 10 * res_ns)
        assert target.points == pytest.approx(1.0)
        assert target.alert_count == 2
        assert target.top_rule_name == "rule_b"

    def test_tie_break_by_earliest_timestamp(self) -> None:
        res_ns = 60_000_000_000
        range_ns = 3_600_000_000_000
        now_ns = range_ns
        alerts = [
            _alert(10 * res_ns + 500, 0.5, "rule_late", "e"),
            _alert(10 * res_ns + 100, 0.5, "rule_early", "e"),
        ]
        items = _bucket_alerts(alerts, now_ns=now_ns, range_ns=range_ns, res_ns=res_ns)
        target = next(b for b in items if b.bucket_start_ns == 10 * res_ns)
        assert target.top_rule_name == "rule_early"

    def test_boundary_alert_lands_in_later_bucket(self) -> None:
        res_ns = 60_000_000_000
        range_ns = 3_600_000_000_000
        now_ns = range_ns
        alerts = [_alert(10 * res_ns, 0.9, "r", "e")]
        items = _bucket_alerts(alerts, now_ns=now_ns, range_ns=range_ns, res_ns=res_ns)
        assert next(b for b in items if b.bucket_start_ns == 10 * res_ns).alert_count == 1
        assert next(b for b in items if b.bucket_start_ns == 9 * res_ns).alert_count == 0

    def test_item_cardinality_ceil_div(self) -> None:
        res_ns = 15 * 60 * 1_000_000_000
        range_ns = 24 * 3600 * 1_000_000_000
        now_ns = range_ns
        items = _bucket_alerts([], now_ns=now_ns, range_ns=range_ns, res_ns=res_ns)
        assert len(items) == 96

    def test_out_of_window_alerts_are_ignored(self) -> None:
        res_ns = 60_000_000_000
        range_ns = 3_600_000_000_000
        now_ns = range_ns
        # Alert at negative timestamp — outside [0, now_ns).
        alerts = [_alert(-res_ns, 0.9, "stale", "e")]
        items = _bucket_alerts(alerts, now_ns=now_ns, range_ns=range_ns, res_ns=res_ns)
        assert all(b.alert_count == 0 for b in items)
        assert all(b.points == 0.0 for b in items)


class TestEntityRiskHistory:
    """Tests for GET /api/v1/entities/{uuid}/risk-history (S-060.F1)."""

    @pytest.fixture
    def alert_store(self) -> AsyncMock:
        store = AsyncMock()
        store.query_alerts.return_value = Page(items=[], total=0, page=1, limit=10_000)
        return store

    @pytest.fixture
    def client(self, alert_store: AsyncMock) -> TestClient:
        app = FastAPI()
        app.state.storage = StorageDeps(
            log_store=AsyncMock(), alert_store=alert_store, entity_store=AsyncMock()
        )
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    def test_happy_path_returns_zero_filled_series(self, client: TestClient) -> None:
        uuid_str = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{uuid_str}/risk-history?range=1h&resolution=1m")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"] == {
            "range": "1h",
            "resolution": "1m",
            "alert_count_truncated": False,
        }
        assert len(body["items"]) == 60
        assert all(b["points"] == 0.0 for b in body["items"])
        assert all(b["top_rule_name"] == "" for b in body["items"])
        assert all(isinstance(b["bucket_start_ns"], str) for b in body["items"])

    def test_default_resolution_is_smallest_for_range(self, client: TestClient) -> None:
        uuid_str = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{uuid_str}/risk-history?range=24h")
        assert resp.status_code == 200
        assert resp.json()["meta"]["resolution"] == "5m"

    def test_invalid_resolution_for_range_returns_422(self, client: TestClient) -> None:
        uuid_str = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{uuid_str}/risk-history?range=1h&resolution=1h")
        assert resp.status_code == 422
        assert "not allowed" in resp.json()["detail"]

    def test_invalid_range_returns_422(self, client: TestClient) -> None:
        uuid_str = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{uuid_str}/risk-history?range=99d")
        assert resp.status_code == 422

    def test_malformed_uuid_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/entities/not-a-uuid/risk-history?range=1h")
        assert resp.status_code == 422

    def test_entity_uuid_passed_as_string(
        self, client: TestClient, alert_store: AsyncMock
    ) -> None:
        uuid_str = str(uuid.uuid4())
        client.get(f"/api/v1/entities/{uuid_str}/risk-history?range=1h")
        q = alert_store.query_alerts.await_args.args[0]
        assert q.entity_uuid == uuid_str
        assert isinstance(q.entity_uuid, str)

    def test_truncation_flag_surfaces(self, client: TestClient, alert_store: AsyncMock) -> None:
        uuid_str = str(uuid.uuid4())
        alert_store.query_alerts.return_value = Page(items=[], total=10_001, page=1, limit=10_000)
        resp = client.get(f"/api/v1/entities/{uuid_str}/risk-history?range=1h")
        assert resp.json()["meta"]["alert_count_truncated"] is True
