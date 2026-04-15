"""Tests for the alerts REST route."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.alerts import router
from seerflow.models.alert import Alert


def _make_alert(**overrides: object) -> Alert:
    defaults: dict[str, object] = {
        "alert_id": "alert-001",
        "alert_type": "ml",
        "timestamp_ns": 1_000_000_000,
        "severity_id": 4,
        "rule_name": "hst_anomaly",
        "description": "Anomaly detected",
        "entity_uuid": "ent-001",
        "entity_value": "192.168.1.1",
        "entity_type": "ip",
        "contributing_events": (uuid.uuid4(),),
        "risk_score": 0.85,
    }
    defaults.update(overrides)
    return Alert(**defaults)  # type: ignore[arg-type]


def test_list_alerts_severity_param_uses_shared_bounds() -> None:
    """list_alerts severity query constraints must reference the shared
    SEVERITY_MIN/SEVERITY_MAX constants from models.event, not literals."""
    from fastapi.routing import APIRoute

    from seerflow.models.event import SEVERITY_MAX, SEVERITY_MIN

    route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == "/alerts")
    severity_param = next(p for p in route.dependant.query_params if p.name == "severity")
    assert severity_param.field_info.metadata is not None
    ge_values = [m.ge for m in severity_param.field_info.metadata if hasattr(m, "ge")]
    le_values = [m.le for m in severity_param.field_info.metadata if hasattr(m, "le")]
    assert SEVERITY_MIN in ge_values
    assert SEVERITY_MAX in le_values


class TestFeedbackNoteRoundTrip:
    """Feedback note persists via POST and surfaces via GET."""

    @pytest.fixture
    def seeded_alert_id(self) -> str:
        return "alert-001"

    @pytest.fixture
    def client(self, seeded_alert_id: str) -> TestClient:
        # Mutable container captures what update_feedback wrote, so the
        # subsequent GET returns an Alert with the persisted note.
        stored: dict[str, tuple[str, str]] = {}
        alert_store = AsyncMock()

        async def _get_alert_by_id(alert_id: str) -> Alert | None:
            if alert_id != seeded_alert_id:
                return None
            feedback, note = stored.get(alert_id, ("", ""))
            return _make_alert(alert_id=alert_id, feedback=feedback, feedback_note=note)

        async def _update_feedback(alert_id: str, feedback: str, note: str = "") -> None:
            stored[alert_id] = (feedback, note)

        alert_store.get_alert_by_id.side_effect = _get_alert_by_id
        alert_store.update_feedback.side_effect = _update_feedback

        app = FastAPI()
        app.state.storage = StorageDeps(
            log_store=AsyncMock(),
            alert_store=alert_store,
        )
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    def test_post_feedback_persists_note(self, client: TestClient, seeded_alert_id: str) -> None:
        resp = client.post(
            f"/api/v1/alerts/{seeded_alert_id}/feedback",
            json={"feedback": "fp", "note": "benign vuln scanner"},
        )
        assert resp.status_code == 204

        detail = client.get(f"/api/v1/alerts/{seeded_alert_id}")
        assert detail.status_code == 200
        assert detail.json()["feedback_note"] == "benign vuln scanner"

    def test_post_feedback_without_note_defaults_empty(
        self, client: TestClient, seeded_alert_id: str
    ) -> None:
        resp = client.post(
            f"/api/v1/alerts/{seeded_alert_id}/feedback",
            json={"feedback": "tp"},
        )
        assert resp.status_code == 204

        detail = client.get(f"/api/v1/alerts/{seeded_alert_id}")
        assert detail.status_code == 200
        assert detail.json()["feedback_note"] == ""

    def test_note_exceeding_512_chars_rejected(
        self, client: TestClient, seeded_alert_id: str
    ) -> None:
        resp = client.post(
            f"/api/v1/alerts/{seeded_alert_id}/feedback",
            json={"feedback": "fp", "note": "x" * 513},
        )
        assert resp.status_code == 422

    def test_note_control_chars_stripped(self, client: TestClient, seeded_alert_id: str) -> None:
        resp = client.post(
            f"/api/v1/alerts/{seeded_alert_id}/feedback",
            json={"feedback": "fp", "note": "line1\nline2\x00evil"},
        )
        assert resp.status_code == 204

        detail = client.get(f"/api/v1/alerts/{seeded_alert_id}")
        note = detail.json()["feedback_note"]
        assert "\x00" not in note
        assert "\n" not in note
