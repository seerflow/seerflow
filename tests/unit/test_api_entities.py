"""Tests for the FastAPI entity search endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.entities import router
from seerflow.models.entity import generate_ip_id
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import EntityRelation, Page


def _make_app(
    log_store: AsyncMock,
    entity_store: AsyncMock | None = None,
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
        from seerflow.models.entity import generate_ip_id

        return str(generate_ip_id(value))
    if entity_type == "user":
        from seerflow.models.entity import generate_user_id, normalize_username

        username, domain = normalize_username(value)
        return str(generate_user_id(username, domain))
    if entity_type == "host":
        from seerflow.models.entity import generate_host_id

        return str(generate_host_id(value))
    if entity_type == "domain":
        from seerflow.models.entity import generate_domain_id

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


from seerflow.api.routes.entities import DEFAULT_TIMELINE_WINDOW_NS


def _make_timeline_app(
    entity_store: AsyncMock | None,
    log_store: AsyncMock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.storage = StorageDeps(
        log_store=log_store or AsyncMock(),
        alert_store=AsyncMock(),
        entity_store=entity_store,
    )
    app.include_router(router, prefix="/api/v1")
    return app


class TestEntityTimeline:
    """GET /api/v1/entities/{entity_uuid}/timeline."""

    def test_happy_path_returns_events_and_related(self) -> None:
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
        entity_store = AsyncMock()
        entity_store.get_timeline.return_value = [event]
        entity_store.get_related.return_value = [relation]

        client = TestClient(_make_timeline_app(entity_store))
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

    def test_default_time_range_spans_last_24h(self) -> None:
        entity_uuid = str(uuid.uuid4())
        entity_store = AsyncMock()
        entity_store.get_timeline.return_value = []
        entity_store.get_related.return_value = []

        client = TestClient(_make_timeline_app(entity_store))
        resp = client.get(f"/api/v1/entities/{entity_uuid}/timeline")
        assert resp.status_code == 200
        call = entity_store.get_timeline.await_args
        time_range = call.kwargs["time_range"]
        assert time_range.end_ns - time_range.start_ns == DEFAULT_TIMELINE_WINDOW_NS
