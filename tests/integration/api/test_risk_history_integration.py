"""End-to-end test for GET /api/v1/entities/{uuid}/risk-history (S-060.F1)."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.anomaly_timeline import RESOLUTION_NS
from seerflow.api.app import create_api_app
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


def _alert_at(
    ts_ns: int,
    *,
    entity: str,
    risk: float = 0.5,
    rule: str = "rule_a",
    dedup_key: str | None = None,
) -> Alert:
    # Unique dedup_key per alert prevents the SQLite backend's dedup upsert
    # from collapsing distinct test alerts into a single row.
    key = dedup_key if dedup_key is not None else f"risk-history-{uuid.uuid4()}"
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="correlation",
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.ERROR,
        rule_name=rule,
        description="integration risk-history",
        entity_uuid=entity,
        entity_value="e",
        entity_type="user",
        contributing_events=(uuid.uuid4(),),
        risk_score=risk,
        dedup_key=key,
    )


@pytest.fixture
def client(backend: SqliteBackend) -> TestClient:
    app = create_api_app(log_store=backend, alert_store=backend, entity_store=backend)
    return TestClient(app)


@pytest.mark.asyncio
class TestRiskHistoryIntegration:
    async def test_buckets_sum_and_top_rule(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        res_ns = RESOLUTION_NS["1m"]
        now_bucket = (time.time_ns() // res_ns) * res_ns
        entity = str(uuid.uuid5(uuid.NAMESPACE_DNS, "alice-risk-history"))

        # Two alerts in the same bucket (now - 1 minute) with different risks.
        await backend.write_alert(
            _alert_at(now_bucket - res_ns + 100, entity=entity, risk=0.3, rule="low"),
            dedup_window_ns=0,
        )
        await backend.write_alert(
            _alert_at(now_bucket - res_ns + 200, entity=entity, risk=0.9, rule="high"),
            dedup_window_ns=0,
        )

        resp = client.get(f"/api/v1/entities/{entity}/risk-history?range=1h&resolution=1m")
        assert resp.status_code == 200
        body = resp.json()
        target = next(b for b in body["items"] if int(b["bucket_start_ns"]) == now_bucket - res_ns)
        assert target["points"] == pytest.approx(1.2)
        assert target["alert_count"] == 2
        assert target["top_rule_name"] == "high"

    async def test_zero_alerts_returns_all_zero_series(self, client: TestClient) -> None:
        entity = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity}/risk-history?range=1h")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 60
        assert all(b["points"] == 0.0 for b in body["items"])
        assert body["meta"]["alert_count_truncated"] is False

    async def test_other_entity_alerts_do_not_leak(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        res_ns = RESOLUTION_NS["1m"]
        now_bucket = (time.time_ns() // res_ns) * res_ns
        e1 = str(uuid.uuid5(uuid.NAMESPACE_DNS, "isolation-e1"))
        e2 = str(uuid.uuid5(uuid.NAMESPACE_DNS, "isolation-e2"))
        await backend.write_alert(
            _alert_at(now_bucket - res_ns + 1, entity=e2, risk=0.9),
            dedup_window_ns=0,
        )
        resp = client.get(f"/api/v1/entities/{e1}/risk-history?range=1h")
        body = resp.json()
        assert all(b["points"] == 0.0 for b in body["items"])
