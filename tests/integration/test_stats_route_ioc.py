"""Integration test for /api/v1/stats ioc_enrichment field (S-069)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.metrics import PipelineMetrics
from seerflow.api.routes.stats import router
from seerflow.models.query import Page
from seerflow.threat_intel.enricher import IoCEnrichmentMetrics


@pytest.mark.integration
def test_stats_route_includes_ioc_enrichment_block() -> None:
    fake_metrics = PipelineMetrics(
        started_monotonic=0.0,
        total_events_processed=10,
        active_sources=1,
        model_count=4,
        ioc_enrichment=IoCEnrichmentMetrics(
            alerts_emitted_total=2,
            alerts_deduped_total=1,
            dropped_entity_uuid_lookups_total=0,
            risk_register_updates_total=2,
        ),
    )
    log_store = AsyncMock()
    log_store.query_events.return_value = Page(items=(), total=10, page=1, limit=1)
    alert_store = AsyncMock()
    alert_store.query_alerts.return_value = Page(items=(), total=0, page=1, limit=1)
    alert_store.get_feedback_stats.return_value = {}
    alert_store.count_by_severity.return_value = {}

    app = FastAPI()
    app.state.storage = StorageDeps(log_store=log_store, alert_store=alert_store)

    def _provider() -> PipelineMetrics:
        return fake_metrics

    app.state.pipeline_metrics_provider = _provider
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ioc_enrichment"] == {
        "alerts_emitted_total": 2,
        "alerts_deduped_total": 1,
        "dropped_entity_uuid_lookups_total": 0,
        "risk_register_updates_total": 2,
    }
