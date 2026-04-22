"""Integration tests for GET /api/v1/entities/{uuid}/baseline."""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.models.event import SeerflowEvent
from seerflow.ueba.baseline import UEBAParams
from seerflow.ueba.store import BaselineStore

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


UUID_OK = "11111111-1111-5111-8111-111111111111"
UUID_BAD = "not-a-uuid"


def _make_store(*, warmup_days: int = 7, warmup_min_events: int = 50) -> BaselineStore:
    params = UEBAParams(
        alpha=0.05,
        source_ip_cap=8,
        template_top_k=8,
        warmup_days=warmup_days,
        warmup_min_events=warmup_min_events,
    )
    return BaselineStore(params=params, max_entities=16)


def _mk_event(ts_ns: int, uuid: str = UUID_OK) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=_uuid.uuid4(),
        timestamp_ns=ts_ns,
        observed_ns=ts_ns,
        otel_severity=9,
        related_ips=("10.0.0.1",),
        entity_refs=(uuid,),
        template_id=1,
    )


@pytest.fixture
def client_empty(backend: SqliteBackend) -> TestClient:
    """Client with an empty BaselineStore attached."""
    app = create_api_app(log_store=backend, alert_store=backend)
    app.state.baseline_store = _make_store()
    return TestClient(app)


@pytest.fixture
def client_warming(backend: SqliteBackend) -> TestClient:
    """Client with a store containing a not-yet-warm entity."""
    app = create_api_app(log_store=backend, alert_store=backend)
    store = _make_store()
    store.snapshot_and_learn(_mk_event(1_000), entity_types=("ip",))
    app.state.baseline_store = store
    return TestClient(app)


@pytest.fixture
def client_warm(backend: SqliteBackend) -> TestClient:
    """Client with a store containing a fully-warmed entity."""
    app = create_api_app(log_store=backend, alert_store=backend)
    store = _make_store(warmup_days=1, warmup_min_events=3)
    for i in range(4):
        store.snapshot_and_learn(
            _mk_event(i * 86_400 * 1_000_000_000),
            entity_types=("ip",),
        )
    app.state.baseline_store = store
    return TestClient(app)


def test_baseline_unknown_entity_returns_404(client_empty: TestClient) -> None:
    r = client_empty.get(f"/api/v1/entities/{UUID_OK}/baseline")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown entity"


def test_baseline_warming_up_payload(client_warming: TestClient) -> None:
    r = client_warming.get(f"/api/v1/entities/{UUID_OK}/baseline")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "warming_up"
    assert body["events_observed"] == 1
    assert body["events_required"] == 50
    assert "days_observed" in body
    assert body["days_required"] == 7


def test_baseline_warming_up_payload_reflects_custom_params(
    backend: SqliteBackend,
) -> None:
    """Warming-up payload must report the store's live UEBAParams, not constants."""
    app = create_api_app(log_store=backend, alert_store=backend)
    store = _make_store(warmup_days=3, warmup_min_events=10)
    store.snapshot_and_learn(_mk_event(1_000), entity_types=("ip",))
    app.state.baseline_store = store
    client = TestClient(app)

    r = client.get(f"/api/v1/entities/{UUID_OK}/baseline")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "warming_up"
    assert body["events_required"] == 10
    assert body["days_required"] == 3


def test_baseline_warm_returns_payload(client_warm: TestClient) -> None:
    r = client_warm.get(f"/api/v1/entities/{UUID_OK}/baseline")
    assert r.status_code == 200
    body = r.json()
    assert body["entity_uuid"] == UUID_OK
    assert len(body["hours"]) == 24


def test_baseline_invalid_uuid_returns_422(client_empty: TestClient) -> None:
    r = client_empty.get(f"/api/v1/entities/{UUID_BAD}/baseline")
    assert r.status_code == 422


def test_baseline_503_when_ueba_disabled(backend: SqliteBackend) -> None:
    """No baseline_store attached => UEBA disabled => 503, not 404.

    404 conflates "entity not found" with "feature disabled". The
    require_entity_store dep (api.deps) already uses 503 for missing
    backends; this route follows the same contract for consistency.
    """
    app = create_api_app(log_store=backend, alert_store=backend)
    app.state.baseline_store = None
    client = TestClient(app)
    r = client.get(f"/api/v1/entities/{UUID_OK}/baseline")
    assert r.status_code == 503
    assert r.json()["detail"] == "UEBA disabled"
