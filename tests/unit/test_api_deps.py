"""Tests for API dependency injection and timestamp parsing."""

from __future__ import annotations

import pytest

from seerflow.api.deps import StorageDeps, parse_timestamp_ns


class TestParseTimestampNs:
    """Tests for ISO-8601 -> nanosecond epoch conversion."""

    def test_utc_iso_string(self) -> None:
        result = parse_timestamp_ns("2026-04-09T12:00:00+00:00")
        assert result == 1_775_736_000_000_000_000

    def test_naive_assumed_utc(self) -> None:
        result = parse_timestamp_ns("2026-04-09T12:00:00")
        assert result == 1_775_736_000_000_000_000

    def test_with_timezone_offset(self) -> None:
        result = parse_timestamp_ns("2026-04-09T14:00:00+02:00")
        assert result == 1_775_736_000_000_000_000

    def test_with_fractional_seconds(self) -> None:
        result = parse_timestamp_ns("2026-04-09T12:00:00.500+00:00")
        assert result == 1_775_736_000_500_000_000

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_timestamp_ns("not-a-date")

    def test_far_future_overflows_raises(self) -> None:
        with pytest.raises(ValueError, match="out of supported range"):
            parse_timestamp_ns("9999-12-31T23:59:59+00:00")


class TestGetPluginInventory:
    """Tests for the get_plugin_inventory Depends provider (S-370)."""

    def test_returns_empty_inventory_when_unset(self) -> None:
        from types import SimpleNamespace

        from seerflow.api.deps import get_plugin_inventory

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        inventory = get_plugin_inventory(request)  # type: ignore[arg-type]
        assert inventory.entries() == ()

    def test_returns_stashed_inventory(self) -> None:
        from types import SimpleNamespace

        from seerflow.api.deps import get_plugin_inventory
        from seerflow.plugins.lifecycle import PluginInventory
        from seerflow.plugins.records import LoadedPlugins

        stashed = PluginInventory(LoadedPlugins())
        state = SimpleNamespace(plugins=stashed)
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        assert get_plugin_inventory(request) is stashed  # type: ignore[arg-type]


class TestStorageDeps:
    """Tests for the StorageDeps container."""

    def test_entity_store_defaults_to_none(self) -> None:
        from unittest.mock import AsyncMock

        deps = StorageDeps(log_store=AsyncMock(), alert_store=AsyncMock())
        assert deps.entity_store is None

    def test_all_stores_set(self) -> None:
        from unittest.mock import AsyncMock

        deps = StorageDeps(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            entity_store=AsyncMock(),
        )
        assert deps.log_store is not None
        assert deps.alert_store is not None
        assert deps.entity_store is not None


class TestRequireEntityStore:
    """Tests for the require_entity_store dependency."""

    def test_require_entity_store_raises_503_when_missing(self) -> None:
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        from seerflow.api.deps import require_entity_store

        storage = StorageDeps(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            entity_store=None,
        )
        with pytest.raises(HTTPException) as excinfo:
            require_entity_store(storage)
        assert excinfo.value.status_code == 503
        assert "entity_store" in excinfo.value.detail.lower()

    def test_require_entity_store_returns_store_when_present(self) -> None:
        from unittest.mock import AsyncMock

        from seerflow.api.deps import require_entity_store

        store = AsyncMock()
        storage = StorageDeps(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            entity_store=store,
        )
        result = require_entity_store(storage)
        assert result is store


class TestDetectionEngines:
    def test_defaults(self) -> None:
        from seerflow.api.deps import DetectionEngines

        engines = DetectionEngines()
        assert engines.sigma_engine is None
        assert engines.correlation_rules == ()

    def test_is_frozen(self) -> None:
        import dataclasses

        from seerflow.api.deps import DetectionEngines

        engines = DetectionEngines()
        with pytest.raises(dataclasses.FrozenInstanceError):
            engines.sigma_engine = object()  # type: ignore[misc]

    def test_get_engines_reads_from_app_state(self) -> None:
        from types import SimpleNamespace

        from seerflow.api.deps import DetectionEngines, get_engines

        sentinel = DetectionEngines()
        app = SimpleNamespace(state=SimpleNamespace(engines=sentinel))
        request = SimpleNamespace(app=app)
        assert get_engines(request) is sentinel  # type: ignore[arg-type]


class TestGetPipelineMetricsProvider:
    def test_returns_none_when_not_set(self) -> None:
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from seerflow.api.deps import get_pipeline_metrics_provider

        app = FastAPI()

        @app.get("/probe")
        def probe(
            provider=Depends(get_pipeline_metrics_provider),  # noqa: B008
        ) -> dict:
            return {"has": provider is not None}

        client = TestClient(app)
        resp = client.get("/probe")
        assert resp.status_code == 200
        assert resp.json() == {"has": False}

    def test_returns_provider_when_set(self) -> None:
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from seerflow.api.deps import get_pipeline_metrics_provider
        from seerflow.api.metrics import PipelineMetrics

        app = FastAPI()
        app.state.pipeline_metrics_provider = lambda: PipelineMetrics(
            started_monotonic=0.0,
            total_events_processed=10,
            active_sources=1,
            model_count=4,
        )

        @app.get("/probe")
        def probe(
            provider=Depends(get_pipeline_metrics_provider),  # noqa: B008
        ) -> dict:
            if provider is None:
                return {"has": False}
            m = provider()
            return {"has": True, "events": m.total_events_processed}

        client = TestClient(app)
        resp = client.get("/probe")
        assert resp.status_code == 200
        assert resp.json() == {"has": True, "events": 10}
