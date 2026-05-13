"""Integration tests for the alert explanation endpoints (S-071, FR-056).

Drives the FastAPI app through ``TestClient`` with a real ``AlertStore``
fixture and a ``FakeLLMBackend`` so we never need the ``llama-cpp-python``
wheel installed.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import LLMConfig
from seerflow.llm.explanation.cache import ExplanationCache
from seerflow.llm.explanation.service import AlertExplanationService

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend

# Expose ``tests/unit/llm/explanation/_fakes.py`` as ``_fakes``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit" / "llm" / "explanation"))
from _fakes import (
    FakeLLMBackend,
    make_alert,
    make_event,
)


@pytest.fixture
async def alert_in_store(backend: SqliteBackend) -> str:
    alert = make_alert()
    event = make_event()
    await backend.write_events([event])
    await backend.flush()
    await backend.write_alert(alert)
    return alert.alert_id


@pytest.fixture
def fake_backend() -> FakeLLMBackend:
    return FakeLLMBackend()


@pytest.fixture
def explanation_client(backend: SqliteBackend, fake_backend: FakeLLMBackend) -> TestClient:
    cache = ExplanationCache(max_entries=8, ttl_seconds=60)
    service = AlertExplanationService(
        backend=fake_backend,
        cache=cache,
        cfg=LLMConfig(),
        alert_store=backend,
        log_store=backend,
        baseline_store=None,
    )
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        explanation_service=service,
        health_state={"pipeline": "running", "storage": "connected", "llm": "ready"},
    )
    return TestClient(app)


@pytest.fixture
def no_llm_client(backend: SqliteBackend) -> TestClient:
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        explanation_service=None,
        health_state={"pipeline": "running", "storage": "connected", "llm": "disabled"},
    )
    return TestClient(app)


class TestExplainEndpoint:
    """``POST /api/v1/alerts/{alert_id}/explain``."""

    async def test_post_returns_503_when_service_missing(self, no_llm_client: TestClient) -> None:
        resp = no_llm_client.post(f"/api/v1/alerts/{uuid.uuid4()}/explain")
        assert resp.status_code == 503
        body = resp.json()
        # FastAPI wraps the detail dict under the "detail" key.
        assert body["detail"]["detail"] == "llm_not_ready"
        assert body["detail"]["status"] == "disabled"

    async def test_get_returns_503_when_service_missing(self, no_llm_client: TestClient) -> None:
        resp = no_llm_client.get(f"/api/v1/alerts/{uuid.uuid4()}/explanation")
        assert resp.status_code == 503

    async def test_post_then_get_round_trip(
        self,
        explanation_client: TestClient,
        alert_in_store: str,
        fake_backend: FakeLLMBackend,
    ) -> None:
        resp1 = explanation_client.post(f"/api/v1/alerts/{alert_in_store}/explain")
        assert resp1.status_code == 200, resp1.text
        body1 = resp1.json()
        assert body1["alert_id"] == alert_in_store
        assert body1["summary"]
        assert body1["recommended_next_steps"]
        assert body1["cached"] is False
        assert fake_backend.call_count == 1

        # Second POST → cache hit.
        resp2 = explanation_client.post(f"/api/v1/alerts/{alert_in_store}/explain")
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["cached"] is True
        assert fake_backend.call_count == 1

        # GET returns the cached body.
        resp3 = explanation_client.get(f"/api/v1/alerts/{alert_in_store}/explanation")
        assert resp3.status_code == 200
        body3 = resp3.json()
        assert body3["cached"] is True
        # Section payloads match.
        assert body3["summary"] == body2["summary"]
        assert body3["recommended_next_steps"] == body2["recommended_next_steps"]

    async def test_post_unknown_alert_returns_404(
        self, explanation_client: TestClient, fake_backend: FakeLLMBackend
    ) -> None:
        resp = explanation_client.post(f"/api/v1/alerts/{uuid.uuid4()}/explain")
        assert resp.status_code == 404
        assert fake_backend.call_count == 0

    async def test_get_unknown_alert_returns_404_with_no_cache_detail(
        self, explanation_client: TestClient
    ) -> None:
        resp = explanation_client.get(f"/api/v1/alerts/{uuid.uuid4()}/explanation")
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"] == "no_cached_explanation"

    async def test_post_502_when_backend_raises(
        self, backend: SqliteBackend, alert_in_store: str
    ) -> None:
        broken = FakeLLMBackend(raise_exc=RuntimeError("inference died"))
        cache = ExplanationCache(max_entries=8, ttl_seconds=60)
        service = AlertExplanationService(
            backend=broken,
            cache=cache,
            cfg=LLMConfig(),
            alert_store=backend,
            log_store=backend,
            baseline_store=None,
        )
        app = create_api_app(
            log_store=backend,
            alert_store=backend,
            explanation_service=service,
            health_state={"pipeline": "running", "storage": "connected", "llm": "ready"},
        )
        client = TestClient(app)
        resp = client.post(f"/api/v1/alerts/{alert_in_store}/explain")
        assert resp.status_code == 502
        assert resp.json()["detail"] == "llm_failed"
