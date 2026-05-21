"""Tests for the FastAPI health endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    import pytest

from seerflow.api.deps import DetectionEngines, StorageDeps
from seerflow.api.latency import StageLatencyTracker
from seerflow.api.metrics import PipelineMetrics
from seerflow.api.routes.health import router
from seerflow.models.query import Page


def _make_app(health_state: dict[str, str]) -> FastAPI:
    app = FastAPI()
    app.state.health_state = health_state
    app.state.engines = DetectionEngines()
    alert_store = MagicMock()
    alert_store.get_feedback_stats = AsyncMock(return_value={"tp": 0, "fp": 0})
    alert_store.query_alerts = AsyncMock(return_value=Page(items=[], total=0, page=1, limit=1))
    app.state.storage = StorageDeps(log_store=MagicMock(), alert_store=alert_store)
    app.state.pipeline_metrics_provider = None
    app.state.stage_latency_tracker = None
    app.include_router(router, prefix="/api/v1")
    return app


def _make_app_with_extras(
    *,
    ensemble: object | None,
    alert_store: object | None = None,
) -> FastAPI:
    """Build a minimal app for health-route tests.

    ``alert_store`` defaults to a stub returning empty feedback stats — the
    route now relies on the contract that ``StorageDeps.alert_store`` is
    always present (matches the ``create_api_app`` factory signature).
    """
    app = FastAPI()
    app.state.health_state = {"pipeline": "running", "storage": "connected"}
    app.state.engines = DetectionEngines(
        sigma_engine=None,
        correlation_rules=(),
        ensemble=ensemble,
    )
    if alert_store is None:
        alert_store = MagicMock()
        alert_store.get_feedback_stats = AsyncMock(return_value={})
        alert_store.query_alerts = AsyncMock(return_value=Page(items=[], total=0, page=1, limit=1))
    elif not hasattr(alert_store, "query_alerts") or not isinstance(
        getattr(alert_store, "query_alerts", None), AsyncMock
    ):
        alert_store.query_alerts = AsyncMock(  # type: ignore[attr-defined]
            return_value=Page(items=[], total=0, page=1, limit=1)
        )
    app.state.storage = StorageDeps(log_store=MagicMock(), alert_store=alert_store)
    app.state.pipeline_metrics_provider = None
    app.state.stage_latency_tracker = None
    app.include_router(router, prefix="/api/v1")
    return app


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    def test_all_healthy_returns_200(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["components"]["pipeline"] == "running"

    def test_degraded_returns_503(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "error"})
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "degraded"

    def test_ok_status_counts_as_healthy(self) -> None:
        app = _make_app({"pipeline": "ok"})
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


class TestHealthEndpointExtras:
    """S-217 — /api/v1/health surfaces detection + feedback when wired."""

    def test_includes_detection_when_ensemble_wired(self) -> None:
        ensemble = MagicMock()
        ensemble.get_health.return_value = {"detectors": 4, "models_loaded": 7}
        alert_store = MagicMock()
        alert_store.get_feedback_stats = AsyncMock(return_value={"tp": 1, "fp": 2})
        client = TestClient(_make_app_with_extras(ensemble=ensemble, alert_store=alert_store))

        body = client.get("/api/v1/health").json()
        assert body["detection"] == {"detectors": 4, "models_loaded": 7}
        assert body["feedback"] == {"tp": 1, "fp": 2}

    def test_detection_is_none_when_ensemble_missing(self) -> None:
        """When no ``DetectionEnsemble`` is wired, ``detection`` falls back to ``None``;
        ``feedback`` always populates because ``alert_store`` is non-Optional by contract."""
        client = TestClient(_make_app_with_extras(ensemble=None))
        body = client.get("/api/v1/health").json()
        assert body["detection"] is None
        assert body["feedback"] == {}


class TestHealthEndpointComprehensive:
    """S-080 — comprehensive health envelope: throughput, latency, memory."""

    def test_response_zero_when_no_provider(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        # Pipeline metrics fields default to zero when no provider is wired.
        assert body["uptime_seconds"] == 0.0
        assert body["event_rate_per_sec"] == 0.0
        assert body["active_sources"] == 0
        assert body["model_count"] == 0

    def test_response_includes_pipeline_metrics_when_provider_wired(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})

        def _provider() -> PipelineMetrics:
            return PipelineMetrics(
                started_monotonic=0.0,  # very long uptime
                total_events_processed=1500,
                active_sources=3,
                model_count=12,
            )

        app.state.pipeline_metrics_provider = _provider
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["uptime_seconds"] > 0.0
        assert body["event_rate_per_sec"] >= 0.0
        assert body["active_sources"] == 3
        assert body["model_count"] == 12

    def test_alert_count_24h_present(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        # Override the stub to return a non-zero total.
        app.state.storage.alert_store.query_alerts = AsyncMock(
            return_value=Page(items=[], total=42, page=1, limit=1)
        )
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["alert_count_24h"] == 42

    def test_alert_count_24h_uses_cache_within_ttl(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        page = Page(items=[], total=7, page=1, limit=1)
        alert_store = app.state.storage.alert_store
        alert_store.query_alerts = AsyncMock(return_value=page)
        client = TestClient(app)
        # Two requests inside the 5s TTL window should hit the store once.
        client.get("/api/v1/health")
        client.get("/api/v1/health")
        assert alert_store.query_alerts.await_count == 1

    def test_alert_count_24h_returns_minus_one_on_error(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        app.state.storage.alert_store.query_alerts = AsyncMock(
            side_effect=RuntimeError("postgresql://u:LEAKED@h/d down")
        )
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        # Endpoint must stay 200 even if alert store hiccups.
        assert resp.status_code == 200
        body = resp.json()
        assert body["alert_count_24h"] == -1

    def test_latency_empty_when_no_tracker(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["latency_ms"] == {}

    def test_latency_snapshot_returned_when_tracker_wired(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        tracker = StageLatencyTracker()
        for v in (1.0, 2.0, 3.0, 4.0, 5.0):
            tracker.record("parse", v)
        for v in (10.0, 20.0, 30.0, 40.0, 50.0):
            tracker.record("detect", v)
        app.state.stage_latency_tracker = tracker
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert set(body["latency_ms"].keys()) == {"parse", "detect"}
        parse = body["latency_ms"]["parse"]
        assert parse["count"] == 5.0
        assert {"p50", "p95", "p99", "count"} <= set(parse.keys())

    def test_memory_bytes_includes_rss(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert "memory_bytes" in body
        assert body["memory_bytes"]["rss"] >= 0

    def test_memory_bytes_includes_model_estimate(self) -> None:
        ensemble = MagicMock()
        ensemble.get_health.return_value = {
            "detectors": 4,
            "estimated_memory_bytes": 123_456,
        }
        alert_store = MagicMock()
        alert_store.get_feedback_stats = AsyncMock(return_value={})
        alert_store.query_alerts = AsyncMock(return_value=Page(items=[], total=0, page=1, limit=1))
        app = _make_app_with_extras(ensemble=ensemble, alert_store=alert_store)
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["memory_bytes"]["models"] == 123_456

    def test_components_per_class_keys_pass_through(self) -> None:
        """Per-component contract: each `health_state` key is preserved verbatim."""
        app = _make_app(
            {
                "pipeline": "running",
                "storage.sqlite": "connected",
                "ml.hst": "ok",
                "ml.holt_winters": "ok",
                "ml.cusum": "ok",
                "ml.markov": "ok",
                "receiver.cloudwatch": "running",
                "parser.drain3": "ok",
            }
        )
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["status"] == "healthy"
        assert "storage.sqlite" in body["components"]
        assert "ml.holt_winters" in body["components"]

    def test_rss_units_normalized_to_bytes_on_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On Linux ``ru_maxrss`` is in KiB; the response must multiply by 1024."""
        from seerflow.api.routes import health as health_route

        class _FakeUsage:
            ru_maxrss = 4096  # 4096 KiB on Linux -> 4_194_304 bytes

        monkeypatch.setattr(health_route, "_PLATFORM", "linux")
        monkeypatch.setattr(
            health_route.resource,
            "getrusage",
            lambda _w: _FakeUsage(),  # type: ignore[arg-type]
        )
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["memory_bytes"]["rss"] == 4096 * 1024

    def test_rss_units_passthrough_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On macOS (Darwin) ``ru_maxrss`` is already in bytes."""
        from seerflow.api.routes import health as health_route

        class _FakeUsage:
            ru_maxrss = 4_194_304

        monkeypatch.setattr(health_route, "_PLATFORM", "darwin")
        monkeypatch.setattr(
            health_route.resource,
            "getrusage",
            lambda _w: _FakeUsage(),  # type: ignore[arg-type]
        )
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        body = client.get("/api/v1/health").json()
        assert body["memory_bytes"]["rss"] == 4_194_304


class TestHealthServerSideProcessTime:
    """S-233: the route reports its own processing duration so callers can
    budget the *endpoint's* work (FR-047) rather than the client round-trip.
    """

    def test_health_emits_server_side_process_time_header(self) -> None:
        """The ``X-Process-Time-Ms`` header carries the route's own
        wall-clock processing duration (float ms), present on the 200 path.
        """
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)

        resp = client.get("/api/v1/health")

        assert resp.status_code == 200
        assert "x-process-time-ms" in resp.headers
        value = float(resp.headers["x-process-time-ms"])
        assert value >= 0.0
        # Server-side work for the bare envelope is trivially under the
        # FR-047 50 ms budget even with coverage instrumentation.
        assert value < 50.0

    def test_process_time_header_present_on_degraded_503(self) -> None:
        """The header is set unconditionally before the single ``return``,
        so it is also present on the 503 degraded path.
        """
        app = _make_app({"pipeline": "running", "storage": "error"})
        client = TestClient(app)

        resp = client.get("/api/v1/health")

        assert resp.status_code == 503
        assert "x-process-time-ms" in resp.headers
        assert float(resp.headers["x-process-time-ms"]) >= 0.0
