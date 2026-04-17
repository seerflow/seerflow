"""Integration test: GET /api/v1/anomaly/timeline with real SqliteBackend.

End-to-end: seed scored events into the app's AnomalyTimelineRing via
``ConnectionManager.broadcast_event`` + seed alerts into real SQLite, then
hit the REST endpoint and verify the bucket shape and the alert_count join.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.anomaly_timeline import BUCKET_NS
from seerflow.api.app import create_api_app
from seerflow.detection.ensemble import DetectionResult
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
def client(backend: SqliteBackend) -> TestClient:
    app = create_api_app(log_store=backend, alert_store=backend)
    return TestClient(app)


def _event_at(ts_ns: int, source: str = "syslog") -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=ts_ns,
        observed_ns=ts_ns + 1,
        message="integration timeline",
        source_type=source,
        severity_id=SeverityLevel(3),
        template_id=7,
    )


def _alert_at(ts_ns: int, dedup_key: str = "") -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.ERROR,
        rule_name="hst_anomaly",
        description="timeline integration alert",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "10.0.0.1")),
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        risk_score=0.9,
        dedup_key=dedup_key,
    )


class TestAnomalyTimelineIntegration:
    async def test_end_to_end_timeline_joins_events_and_alerts(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        # Anchor near wall-clock now so the 1h window covers the event.
        now_bucket = (time.time_ns() // BUCKET_NS) * BUCKET_NS
        ts = now_bucket - BUCKET_NS

        # Seed a scored event into the ring via the real WS broadcast path.
        ws_manager = client.app.state.ws_manager
        ws_manager.broadcast_event(
            _event_at(ts, "syslog"),
            detection=DetectionResult(
                score=0.7,
                upper_threshold=0.9,
                lower_threshold=0.0,
                is_anomaly=False,
                anomaly_direction=None,
                source_type="syslog",
            ),
        )

        # Seed an alert in the same bucket via the real SQLite store.
        await backend.write_alert(_alert_at(ts + 100), dedup_window_ns=0)

        resp = client.get("/api/v1/anomaly/timeline?range=1h&resolution=1m")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"] == {
            "range": "1h",
            "resolution": "1m",
            "source": None,
            "alert_count_truncated": False,
        }
        assert isinstance(body["items"], list)
        assert len(body["items"]) == 60

        target = next(b for b in body["items"] if b["bucket_start_ns"] == ts)
        assert target["event_count"] == 1
        assert target["max_score"] == pytest.approx(0.7)
        assert target["upper_threshold"] == pytest.approx(0.9)
        assert target["alert_count"] == 1

    async def test_alert_count_truncated_when_over_limit(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        from seerflow.api.routes.anomaly import _ALERT_QUERY_LIMIT

        # Anchor near wall-clock now so the 1h window covers the event.
        now_bucket = (time.time_ns() // BUCKET_NS) * BUCKET_NS
        ts_base = now_bucket - BUCKET_NS

        # Seed a scored event into the ring via the real WS broadcast path.
        ws_manager = client.app.state.ws_manager
        ws_manager.broadcast_event(
            _event_at(ts_base, "syslog"),
            detection=DetectionResult(
                score=0.8,
                upper_threshold=0.9,
                lower_threshold=0.0,
                is_anomaly=True,
                anomaly_direction=None,
                source_type="syslog",
            ),
        )

        # Seed _ALERT_QUERY_LIMIT + 50 alerts with unique dedup_keys so each
        # alert is stored as a distinct row (dedup_window_ns=0 disables dedup).
        total_alerts = _ALERT_QUERY_LIMIT + 50
        for i in range(total_alerts):
            await backend.write_alert(
                _alert_at(ts_base + i, dedup_key=f"trunc-test-{i}"),
                dedup_window_ns=0,
            )

        resp = client.get("/api/v1/anomaly/timeline?range=1h&resolution=1m")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["alert_count_truncated"] is True
