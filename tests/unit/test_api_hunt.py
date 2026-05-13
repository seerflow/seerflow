"""Unit tests for the ``POST /api/v1/hunt`` route (S-072, FR-057).

Drives the route through ``TestClient`` with a fake hunt service so we never
hit a real LLM backend or storage layer.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.llm.hunt.result import HuntResult
from seerflow.models.event import SeerflowEvent

if TYPE_CHECKING:
    from seerflow.storage.protocols import AlertStore, LogStore


class _FakeLogStore:
    async def query_events(self, *_a: object, **_kw: object) -> Any:
        raise NotImplementedError

    async def write_events(self, *_a: object, **_kw: object) -> None:
        raise NotImplementedError

    async def search_text(self, *_a: object, **_kw: object) -> Any:
        raise NotImplementedError

    async def flush(self) -> None:
        return None


class _FakeAlertStore:
    async def write_alert(self, *_a: object, **_kw: object) -> bool:
        return False

    async def query_alerts(self, *_a: object, **_kw: object) -> Any:
        raise NotImplementedError

    async def update_feedback(self, *_a: object, **_kw: object) -> None:
        return None

    async def get_alert_by_id(self, *_a: object, **_kw: object) -> Any:
        return None

    async def count_alerts_bucketed(self, *_a: object, **_kw: object) -> Any:
        return []

    async def get_feedback_stats(self) -> dict[str, int]:
        return {}

    async def append_feedback_event(self, *_a: object, **_kw: object) -> None:
        return None

    async def list_feedback_events(self, *_a: object, **_kw: object) -> Any:
        raise NotImplementedError

    async def count_by_severity(self) -> dict[str, int]:
        return {}


class _FakeHuntService:
    """Captures the last call and returns a canned result."""

    def __init__(
        self,
        *,
        result: HuntResult | None = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._result = result
        self._raise_exc = raise_exc
        self.call_count = 0
        self.last_query: str | None = None

    async def hunt(self, nl_query: str) -> HuntResult:
        self.call_count += 1
        self.last_query = nl_query
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._result is None:
            return HuntResult(
                query=nl_query,
                filters={"text_query": nl_query},
                events=(),
                total=0,
                model="fake_llm",
                generated_at_ns=0,
                latency_ms=1.5,
                cached=False,
                truncated=False,
            )
        return self._result


def _event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="ssh login",
        source_type="auth",
    )


def _build_client(
    *,
    hunt_service: _FakeHuntService | None,
    llm_state: str = "ready",
) -> TestClient:
    log: LogStore = _FakeLogStore()  # type: ignore[assignment]
    al: AlertStore = _FakeAlertStore()  # type: ignore[assignment]
    app = create_api_app(
        log_store=log,
        alert_store=al,
        hunt_service=hunt_service,  # type: ignore[arg-type]
        health_state={
            "pipeline": "running",
            "storage": "connected",
            "llm": llm_state,
        },
    )
    return TestClient(app)


@pytest.mark.unit
def test_hunt_200_returns_filters_and_events() -> None:
    result = HuntResult(
        query="ssh from external",
        filters={"text_query": "ssh"},
        events=(_event(),),
        total=1,
        model="fake_llm",
        generated_at_ns=1_700_000_000_000_000_000,
        latency_ms=2.5,
        cached=False,
        truncated=False,
    )
    svc = _FakeHuntService(result=result)
    client = _build_client(hunt_service=svc)
    resp = client.post("/api/v1/hunt", json={"query": "ssh from external"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "ssh from external"
    assert body["filters"] == {"text_query": "ssh"}
    assert body["total"] == 1
    assert len(body["events"]) == 1
    assert body["cached"] is False
    assert body["model"] == "fake_llm"
    assert svc.call_count == 1
    assert svc.last_query == "ssh from external"


@pytest.mark.unit
def test_hunt_503_when_service_missing() -> None:
    client = _build_client(hunt_service=None, llm_state="disabled")
    resp = client.post("/api/v1/hunt", json={"query": "ssh"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["detail"] == "llm_not_ready"
    assert body["detail"]["status"] == "disabled"


@pytest.mark.unit
def test_hunt_503_state_reflects_degraded() -> None:
    client = _build_client(hunt_service=None, llm_state="degraded")
    resp = client.post("/api/v1/hunt", json={"query": "ssh"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["status"] == "degraded"


@pytest.mark.unit
def test_hunt_502_on_service_runtime_failure() -> None:
    svc = _FakeHuntService(raise_exc=RuntimeError("boom"))
    client = _build_client(hunt_service=svc)
    resp = client.post("/api/v1/hunt", json={"query": "ssh"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "llm_failed"


@pytest.mark.unit
def test_hunt_502_on_timeout() -> None:
    svc = _FakeHuntService(raise_exc=TimeoutError())
    client = _build_client(hunt_service=svc)
    resp = client.post("/api/v1/hunt", json={"query": "ssh"})
    assert resp.status_code == 502


@pytest.mark.unit
def test_hunt_400_on_value_error_from_service() -> None:
    svc = _FakeHuntService(raise_exc=ValueError("nl_query is too long"))
    client = _build_client(hunt_service=svc)
    resp = client.post("/api/v1/hunt", json={"query": "x" * 50})
    assert resp.status_code == 400
    assert "too long" in resp.json()["detail"]


@pytest.mark.unit
def test_hunt_422_missing_query_field() -> None:
    svc = _FakeHuntService()
    client = _build_client(hunt_service=svc)
    resp = client.post("/api/v1/hunt", json={})
    assert resp.status_code == 422


@pytest.mark.unit
def test_hunt_422_empty_query() -> None:
    svc = _FakeHuntService()
    client = _build_client(hunt_service=svc)
    resp = client.post("/api/v1/hunt", json={"query": ""})
    assert resp.status_code == 422
