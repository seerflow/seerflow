"""Tests for the GET /api/v1/attack/coverage route handler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.models.query import AlertQuery, Page
from seerflow.sigma.attack import TACTICS

if TYPE_CHECKING:
    import pytest


class _StubAlertStore:
    def __init__(self, alerts: list[Alert] | None = None) -> None:
        self._alerts: list[Alert] = alerts or []

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]:
        return Page(
            items=tuple(self._alerts),
            total=len(self._alerts),
            page=filters.page,
            limit=filters.limit,
        )

    async def write_alert(self, alert: Alert, dedup_window_ns: int = 0) -> bool:
        self._alerts.append(alert)
        return True

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        return next((a for a in self._alerts if a.alert_id == alert_id), None)

    async def update_feedback(self, alert_id: str, feedback: str) -> None:
        return None

    async def get_feedback_stats(self) -> dict[str, int]:
        return {"tp": 0, "fp": 0, "total": 0}


class _StubLogStore:
    async def query_events(self, *args: Any, **kwargs: Any) -> Page[Any]:
        return Page(items=(), total=0, page=1, limit=50)

    async def write_events(self, events: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def search_text(self, *args: Any, **kwargs: Any) -> Page[Any]:
        return Page(items=(), total=0, page=1, limit=50)


def _mitre_alert(tactics: tuple[str, ...], techniques: tuple[str, ...]) -> Alert:
    return Alert(
        alert_id="a1",
        alert_type="sigma",
        timestamp_ns=1_775_736_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="test",
        description="",
        entity_uuid="e",
        entity_value="v",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


def _build_client(alerts: list[Alert] | None = None) -> TestClient:
    app = create_api_app(
        log_store=_StubLogStore(),  # type: ignore[arg-type]
        alert_store=_StubAlertStore(alerts),  # type: ignore[arg-type]
    )
    return TestClient(app)


class TestAttackCoverageRoute:
    def test_empty_engine_returns_200_with_all_known_tactics(self) -> None:
        client = _build_client()
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        assert [t["tactic"] for t in body["tactics"]] == list(TACTICS.keys())
        assert body["summary"] == {
            "total_techniques_covered": 0,
            "total_techniques_detected": 0,
            "total_rules_with_attack_tags": 0,
            "total_alerts_matched": 0,
        }

    def test_counts_alerts_without_sigma_engine(self) -> None:
        client = _build_client(alerts=[_mitre_alert(("discovery",), ("t1033",))])
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        discovery = next(t for t in body["tactics"] if t["tactic"] == "discovery")
        cell = discovery["techniques"][0]
        assert cell["technique"] == "T1033"
        assert cell["alert_count"] == 1
        assert cell["detected"] is True
        assert cell["covered"] is False

    def test_since_after_until_returns_400(self) -> None:
        client = _build_client()
        response = client.get(
            "/api/v1/attack/coverage",
            params={
                "since": "2026-04-11T00:00:00+00:00",
                "until": "2026-03-11T00:00:00+00:00",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "since must be before until"

    def test_malformed_timestamp_returns_422(self) -> None:
        client = _build_client()
        response = client.get("/api/v1/attack/coverage", params={"since": "not-a-date"})
        assert response.status_code == 422

    def test_default_window_is_thirty_days(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        fixed_now = datetime(2026, 4, 11, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
                return fixed_now

        monkeypatch.setattr("seerflow.api.routes.attack.datetime", _FakeDT)
        client = _build_client()
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        assert body["window_until"].startswith("2026-04-11")
        expected_since = fixed_now - timedelta(days=30)
        assert body["window_since"].startswith(expected_since.date().isoformat())
