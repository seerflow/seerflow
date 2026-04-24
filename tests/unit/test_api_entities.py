"""Tests for the FastAPI entity search endpoint."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.entities import DEFAULT_TIMELINE_WINDOW_NS, router
from seerflow.models.entity import (
    generate_domain_id,
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    normalize_username,
)
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import EntityRelation, Page

if TYPE_CHECKING:
    # Protocol is only referenced in annotations; `from __future__ import annotations`
    # above keeps the runtime from evaluating `EntityStore`, so the TYPE_CHECKING guard
    # is safe and satisfies ruff TC001.
    from seerflow.storage.protocols import EntityStore


def _make_app(
    log_store: AsyncMock,
    entity_store: EntityStore | None = None,
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
        assert all("entity_uuid" in r and r["entity_uuid"] for r in results)

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
        assert ip_results[0]["entity_uuid"]


def _expected_uuid(entity_type: str, value: str) -> str:
    """Mirror the route's UUID derivation for assertions."""
    if entity_type == "ip":
        return str(generate_ip_id(value))
    if entity_type == "user":
        username, domain = normalize_username(value)
        return str(generate_user_id(username, domain))
    if entity_type == "host":
        return str(generate_host_id(value))
    if entity_type == "domain":
        return str(generate_domain_id(value))
    raise AssertionError(f"unexpected type {entity_type}")


class TestEntitySearchUuidStamping:
    """UUIDs are stamped on ip/user/host/domain search results."""

    def test_ip_result_carries_derived_uuid(self) -> None:
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_ips=("10.0.0.1",),
        )
        log_store = AsyncMock()
        log_store.search_text.return_value = [event]
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=10.0.0.1")
        assert resp.status_code == 200
        results = resp.json()
        ip_result = next(r for r in results if r["entity_type"] == "ip")
        assert ip_result["entity_uuid"] == _expected_uuid("ip", "10.0.0.1")

    def test_user_host_domain_results_carry_uuid(self) -> None:
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_users=("alice@corp",),
            related_hosts=("web-01",),
            related_domains=("evil.example.com",),
        )
        log_store = AsyncMock()
        log_store.search_text.return_value = [event]
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=alice")
        assert resp.status_code == 200
        results = {(r["entity_type"], r["entity_value"]): r["entity_uuid"] for r in resp.json()}
        assert results[("user", "alice@corp")] == _expected_uuid("user", "alice@corp")
        assert results[("host", "web-01")] == _expected_uuid("host", "web-01")
        assert results[("domain", "evil.example.com")] == _expected_uuid(
            "domain", "evil.example.com"
        )

    def test_files_processes_hashes_not_stamped(self) -> None:
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_files=("/etc/passwd",),
            related_processes=("bash",),
            related_hashes=("sha256:abc",),
        )
        log_store = AsyncMock()
        log_store.search_text.return_value = [event]
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=passwd")
        assert resp.status_code == 200
        types = {r["entity_type"] for r in resp.json()}
        assert "file" not in types
        assert "process" not in types
        assert "hash" not in types

    def test_malformed_value_skipped_without_poisoning_siblings(self) -> None:
        """A malformed IP in a mixed-entity event is skipped; valid siblings survive."""
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_ips=("not-an-ip",),
            related_users=("alice@corp",),
        )
        log_store = AsyncMock()
        log_store.search_text.return_value = [event]
        client = TestClient(_make_app(log_store))
        resp = client.get("/api/v1/entities/search?q=alice")
        assert resp.status_code == 200
        results = resp.json()
        types = {r["entity_type"] for r in results}
        assert "ip" not in types
        assert "user" in types


class TestEntitySearchUuidQuery:
    """UUID-shaped queries short-circuit FTS and use EventQuery(entity_uuid=...)."""

    def test_uuid_query_bypasses_fts(self) -> None:
        target_uuid = str(generate_ip_id("10.0.0.1"))
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_ips=("10.0.0.1",),
        )
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(event,),
            total=1,
            page=1,
            limit=100,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get(f"/api/v1/entities/search?q={target_uuid}")
        assert resp.status_code == 200
        log_store.search_text.assert_not_called()
        log_store.query_events.assert_awaited_once()
        call_args = log_store.query_events.call_args.args[0]
        assert call_args.entity_uuid == target_uuid
        matching = [r for r in resp.json() if r["entity_uuid"] == target_uuid]
        assert len(matching) == 1
        assert matching[0]["entity_type"] == "ip"

    def test_uuid_query_no_events_returns_empty(self) -> None:
        target_uuid = str(uuid.uuid4())
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=100,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get(f"/api/v1/entities/search?q={target_uuid}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_uuid_query_for_non_pivot_entity_returns_empty(self) -> None:
        """Process/file/hash entities are not pivots; their UUID queries return []."""
        process_uuid = str(uuid.uuid4())
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
            related_processes=("bash",),
            entity_refs=(process_uuid,),
        )
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(
            items=(event,),
            total=1,
            page=1,
            limit=100,
        )
        client = TestClient(_make_app(log_store))
        resp = client.get(f"/api/v1/entities/search?q={process_uuid}")
        assert resp.status_code == 200
        assert resp.json() == []


class TestEntityTimeline:
    """GET /api/v1/entities/{entity_uuid}/timeline."""

    @pytest.fixture
    def entity_store(self) -> AsyncMock:
        store = AsyncMock()
        store.get_timeline.return_value = []
        store.get_related.return_value = []
        return store

    @pytest.fixture
    def client(self, entity_store: AsyncMock) -> TestClient:
        return TestClient(_make_app(AsyncMock(), entity_store=entity_store))

    def test_happy_path_returns_events_and_related(
        self,
        entity_store: AsyncMock,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_000,
            observed_ns=1_001,
            source_type="syslog",
            message="login failure",
        )
        relation = EntityRelation(
            entity_uuid=str(uuid.uuid4()),
            entity_type="host",
            entity_value="web-01",
            relation_type="seen_on",
        )
        entity_store.get_timeline.return_value = [event]
        entity_store.get_related.return_value = [relation]

        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_uuid"] == entity_uuid
        assert body["total"] == 1
        assert len(body["events"]) == 1
        assert body["events"][0]["source_type"] == "syslog"
        assert body["events"][0]["message"] == "login failure"
        assert len(body["related"]) == 1
        assert body["related"][0]["relation_type"] == "seen_on"

    def test_default_time_range_spans_last_24h(
        self,
        entity_store: AsyncMock,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline")
        assert resp.status_code == 200
        call = entity_store.get_timeline.await_args
        time_range = call.kwargs["time_range"]
        assert time_range.end_ns - time_range.start_ns == DEFAULT_TIMELINE_WINDOW_NS

    def test_source_type_filter_propagates(
        self,
        entity_store: AsyncMock,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?source_type=syslog")
        assert resp.status_code == 200
        assert entity_store.get_timeline.await_args.kwargs["source_type"] == "syslog"

    def test_severity_min_filter_propagates(
        self,
        entity_store: AsyncMock,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?severity_min=4")
        assert resp.status_code == 200
        assert entity_store.get_timeline.await_args.kwargs["severity_min"] == 4

    def test_explicit_time_range_propagates(
        self,
        entity_store: AsyncMock,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?start_ns=1000&end_ns=2000")
        assert resp.status_code == 200
        tr = entity_store.get_timeline.await_args.kwargs["time_range"]
        assert tr.start_ns == 1000
        assert tr.end_ns == 2000

    def test_limit_propagates_and_clamped(
        self,
        entity_store: AsyncMock,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?limit=500")
        assert resp.status_code == 200
        assert entity_store.get_timeline.await_args.kwargs["limit"] == 500

        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?limit=999999")
        assert resp.status_code == 422

    def test_severity_out_of_range_returns_422(
        self,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?severity_min=7")
        assert resp.status_code == 422

    def test_malformed_uuid_returns_422(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get("/api/v1/entities/not-a-uuid/timeline")
        assert resp.status_code == 422

    def test_missing_entity_store_returns_503(self) -> None:
        entity_uuid = str(uuid.uuid4())
        client = TestClient(_make_app(AsyncMock(), entity_store=None))
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline")
        assert resp.status_code == 503
        assert "entity_store" in resp.json()["detail"].lower()

    def test_start_ns_after_end_ns_returns_422(
        self,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?start_ns=5000&end_ns=1000")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "start_ns must be <= end_ns"

    def test_ns_above_int64_ceiling_returns_422(
        self,
        client: TestClient,
    ) -> None:
        """FastAPI rejects start_ns/end_ns > 2**63 - 1 (SQLite int64 ceiling)."""
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline?end_ns=9223372036854775808")
        assert resp.status_code == 422

    def test_empty_related_returns_empty_list(
        self,
        client: TestClient,
    ) -> None:
        entity_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline")
        assert resp.status_code == 200
        assert resp.json()["related"] == []


# --- Risk-history bucket helper (S-060.F1) -----------------------------------

import uuid as _uuid  # noqa: E402, I001 — intentional mid-file import for S-060.F1 tests
from seerflow.api.routes.entities import _bucket_alerts  # noqa: E402
from seerflow.models.alert import Alert  # noqa: E402
from seerflow.models.event import SeverityLevel  # noqa: E402


def _alert(ts_ns: int, risk: float, rule: str, entity: str) -> Alert:
    return Alert(
        alert_id=str(_uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.ERROR,
        rule_name=rule,
        description="test",
        entity_uuid=entity,
        entity_value="e",
        entity_type="user",
        contributing_events=(_uuid.uuid4(),),
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
