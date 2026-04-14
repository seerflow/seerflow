"""Tests for the GET /api/v1/attack/coverage route handler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest  # noqa: TC002
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.models.query import AlertQuery, Page
from seerflow.sigma.attack import TACTICS


class _StubAlertStore:
    def __init__(self, alerts: list[Alert] | None = None) -> None:
        self._alerts: list[Alert] = alerts or []

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]:
        offset = (filters.page - 1) * filters.limit
        page_items = tuple(self._alerts[offset : offset + filters.limit])
        return Page(
            items=page_items,
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


def _build_client(
    alerts: list[Alert] | None = None,
    correlation_rules: tuple[Any, ...] = (),
) -> TestClient:
    app = create_api_app(
        log_store=_StubLogStore(),  # type: ignore[arg-type]
        alert_store=_StubAlertStore(alerts),  # type: ignore[arg-type]
        correlation_rules=correlation_rules,
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

    def test_since_equals_until_accepted_with_empty_window(self) -> None:
        """Zero-length window is accepted (``since <= until``). Alerts in
        a zero-second window are inherently empty, which is useful for
        clients fetching "coverage as of a specific instant" with rule
        counts but no alert data.
        """
        client = _build_client()
        response = client.get(
            "/api/v1/attack/coverage",
            params={
                "since": "2026-04-11T00:00:00+00:00",
                "until": "2026-04-11T00:00:00+00:00",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_alerts_matched"] == 0
        assert body["window_since"] == body["window_until"]

    def test_malformed_timestamp_returns_422(self) -> None:
        client = _build_client()
        response = client.get("/api/v1/attack/coverage", params={"since": "not-a-date"})
        assert response.status_code == 422

    def test_correlation_rules_contribute_to_coverage(self) -> None:
        from seerflow.models.alert import CorrelationRule, SourceCondition

        rule = CorrelationRule(
            name="test",
            entity_type="ip",
            window_seconds=60,
            sources=(SourceCondition(source_type="syslog", conditions={}),),
            min_sources=1,
            alert_severity=SeverityLevel.WARNING,
            mitre_tactics=("lateral_movement",),
            mitre_techniques=("T1021",),
        )
        client = _build_client(correlation_rules=(rule,))
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_rules_with_attack_tags"] == 1
        lat = next(t for t in body["tactics"] if t["tactic"] == "lateral_movement")
        assert lat["techniques"][0]["technique"] == "T1021"
        assert lat["techniques"][0]["covered"] is True

    def test_default_window_is_thirty_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert body["window_until"] == fixed_now.isoformat()
        expected_since = fixed_now - timedelta(days=30)
        assert body["window_since"] == expected_since.isoformat()

    def test_alert_scan_caps_at_max_scan(self) -> None:
        # 10_001 alerts — one past the _MAX_ALERT_SCAN = 10_000 cap. The
        # route issues a single query with limit=10_000, so only the first
        # 10_000 alerts contribute to the coverage matrix.
        alerts = [
            Alert(
                alert_id=f"cap-{i}",
                alert_type="sigma",
                timestamp_ns=1_775_736_000_000_000_000 + i,
                severity_id=SeverityLevel.WARNING,
                rule_name="test",
                description="",
                entity_uuid="e",
                entity_value="v",
                entity_type="ip",
                contributing_events=(),
                mitre_tactics=("discovery",),
                mitre_techniques=("t1033",),
            )
            for i in range(10_001)
        ]
        client = _build_client(alerts=alerts)
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_alerts_matched"] == 10_000
        discovery = next(t for t in body["tactics"] if t["tactic"] == "discovery")
        cell = next(c for c in discovery["techniques"] if c["technique"] == "T1033")
        assert cell["alert_count"] == 10_000

    def test_multi_tag_alert_contributes_cell_hits(self) -> None:
        """An alert tagged with two tactics x two techniques should contribute
        four separate (tactic, technique) cell hits — this is cell-hit
        semantics for ``total_alerts_matched``, documented on the schema.
        """
        alert = Alert(
            alert_id="multi",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e",
            entity_value="v",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("discovery", "execution"),
            mitre_techniques=("t1033", "t1059"),
        )
        client = _build_client(alerts=[alert])
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        # 2 tactics x 2 techniques = 4 cell hits for one alert.
        assert body["summary"]["total_alerts_matched"] == 4
        discovery = next(t for t in body["tactics"] if t["tactic"] == "discovery")
        execution = next(t for t in body["tactics"] if t["tactic"] == "execution")
        assert {c["technique"] for c in discovery["techniques"]} == {"T1033", "T1059"}
        assert {c["technique"] for c in execution["techniques"]} == {"T1033", "T1059"}
