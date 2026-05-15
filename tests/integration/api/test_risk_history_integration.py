"""End-to-end test for GET /api/v1/entities/{uuid}/risk-history (S-060.F1)."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.anomaly_timeline import RESOLUTION_NS
from seerflow.api.app import create_api_app
from seerflow.config import SeerflowConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from tests.conftest import pin_time_ns

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

    async def test_rate_limit_returns_429(self, backend: SqliteBackend) -> None:
        """Exceeding list_limit returns 429.

        Mirrors the S-181 pattern from ``tests/integration/test_api_rate_limit.py``:
        build a dedicated ``TestClient`` with ``api_rate_limit_enabled=True`` and
        a tight ``api_list_rate_limit`` so the third request trips the limiter.
        The module-level autouse ``_reset_api_limiter`` fixture in
        ``tests/conftest.py`` guarantees counters do not leak across tests.
        """
        cfg = SeerflowConfig(
            api_rate_limit_enabled=True,
            api_list_rate_limit="2/minute",
            api_detail_rate_limit="100/minute",
            api_coverage_rate_limit="100/minute",
            api_allowed_origins=("http://localhost:3000",),
        )
        app = create_api_app(
            log_store=backend, alert_store=backend, entity_store=backend, config=cfg
        )
        rl_client = TestClient(app)

        entity = str(uuid.uuid4())
        url = f"/api/v1/entities/{entity}/risk-history?range=1h"
        assert rl_client.get(url).status_code == 200
        assert rl_client.get(url).status_code == 200
        r3 = rl_client.get(url)
        assert r3.status_code == 429, f"Expected 429 after burst, got {r3.status_code}"
        assert "retry-after" in {k.lower() for k in r3.headers}

    async def test_truncation_flag_when_over_limit(
        self,
        client: TestClient,
        backend: SqliteBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """meta.alert_count_truncated is True when >10_000 alerts match.

        The endpoint reads ``time.time_ns()`` to derive ``start_ns =
        now_ns - 1h``. Writing 10_050 alerts with individual SQLite
        commits can exceed 60s under ``--cov`` instrumentation, sliding
        the window past the oldest alerts and dropping ``total`` below
        ``_ALERT_QUERY_LIMIT``. Pin the route's clock to the snapshot
        and cluster timestamps inside a safe sub-window so the
        truncation assertion does not depend on wall-clock progression.

        Clock pinning goes through the shared ``pin_time_ns`` helper in
        ``tests/conftest.py`` (SEE-242) rather than an inline lambda. The
        patch target ``seerflow.api.routes.entities.time.time_ns`` relies
        on ``entities.py`` using ``import time`` (not ``from time import
        time_ns``); a future refactor that switches to a direct
        ``time_ns`` import must update the patch path to
        ``seerflow.api.routes.entities.time_ns``. The target string lives
        at this call site so that coupling stays visible.

        See SEE-246 (root-cause fix) and SEE-242 (shared-helper refactor).
        """
        res_ns = RESOLUTION_NS["1m"]
        now_bucket = (time.time_ns() // res_ns) * res_ns
        # Capture by value into a separate name so the pinned clock is
        # immune to any future reassignment of ``now_bucket`` between this
        # point and the request dispatch (pin_time_ns closes over the value).
        pinned_now_ns = now_bucket
        pin_time_ns(
            monkeypatch,
            "seerflow.api.routes.entities.time.time_ns",
            pinned_now_ns,
        )
        entity = str(uuid.uuid5(uuid.NAMESPACE_DNS, "truncation-flood"))
        # 30 min back from ``now_bucket``; the 10_050 ns spread keeps every
        # alert inside the 1h (= 60 * res_ns) query window with a 30 min
        # safety margin on each side.
        offset_ns = 30 * res_ns
        for i in range(10_050):
            await backend.write_alert(
                _alert_at(
                    now_bucket - offset_ns - i,
                    entity=entity,
                    risk=0.1,
                    rule="flood",
                ),
                dedup_window_ns=0,
            )
        resp = client.get(f"/api/v1/entities/{entity}/risk-history?range=1h&resolution=1m")
        assert resp.status_code == 200
        assert resp.json()["meta"]["alert_count_truncated"] is True
