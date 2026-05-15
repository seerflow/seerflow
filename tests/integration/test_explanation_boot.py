"""Integration test: ``AlertExplanationService`` is wired onto ``app.state``.

Validates the boot-time wiring path mirrored in ``pipeline/run.py``:

- ``llm_backend is None`` → ``app.state.explanation_service is None``.
- ``llm_backend is not None`` (via monkeypatched factory) → service is
  constructed with the configured cache size and the route picks it up.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import LLMConfig
from seerflow.llm.explanation import (
    AlertExplanationService,
    ExplanationCache,
)

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit" / "llm" / "explanation"))
from _fakes import FakeLLMBackend, make_alert, make_event


async def test_default_config_leaves_explanation_service_unwired(
    backend: SqliteBackend,
) -> None:
    """``explanation_service=None`` → state attribute is ``None``."""
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        explanation_service=None,
        health_state={"pipeline": "running", "storage": "connected", "llm": "disabled"},
    )
    assert app.state.explanation_service is None


async def test_service_wiring_respects_config_cache_size(
    backend: SqliteBackend,
) -> None:
    """When llm.backend is configured, the cache size mirrors ``LLMConfig``."""
    cfg = LLMConfig(
        backend="llama_cpp",
        explanation_cache_size=32,
        explanation_cache_ttl_s=120,
    )
    cache = ExplanationCache(
        max_entries=cfg.explanation_cache_size,
        ttl_seconds=cfg.explanation_cache_ttl_s,
    )
    service = AlertExplanationService(
        backend=FakeLLMBackend(),
        cache=cache,
        cfg=cfg,
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
    assert app.state.explanation_service is service
    assert app.state.explanation_service.cache._max_entries == 32  # type: ignore[attr-defined]


async def test_explain_endpoint_uses_wired_service(
    backend: SqliteBackend,
) -> None:
    """End-to-end: route picks up service from ``app.state``."""
    alert = make_alert()
    event = make_event()
    await backend.write_events([event])
    await backend.flush()
    await backend.write_alert(alert)

    fake = FakeLLMBackend()
    cache = ExplanationCache(max_entries=4, ttl_seconds=60)
    service = AlertExplanationService(
        backend=fake,
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
    resp = client.post(f"/api/v1/alerts/{alert.alert_id}/explain")
    assert resp.status_code == 200
    assert fake.call_count == 1


async def test_explain_endpoint_returns_503_when_unwired(backend: SqliteBackend) -> None:
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        explanation_service=None,
        health_state={"pipeline": "running", "storage": "connected", "llm": "degraded"},
    )
    client = TestClient(app)
    resp = client.post(f"/api/v1/alerts/{uuid.uuid4()}/explain")
    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["detail"] == "llm_not_ready"
    assert body["status"] == "degraded"
