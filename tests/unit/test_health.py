"""Unit tests for the health endpoint handler."""

from __future__ import annotations

import json

import pytest

from seerflow.api.health import _HEALTH_STATE_KEY, create_health_app, health_handler


class TestHealthHandlerHealthy:
    """Tests when all components report healthy status."""

    @pytest.fixture
    def app(self):
        return create_health_app()

    @pytest.mark.asyncio
    async def test_returns_200(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_response_is_json(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_response_contains_status_healthy(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_response_contains_components(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "components" in body
        assert "pipeline" in body["components"]
        assert "storage" in body["components"]


class TestHealthHandlerDegraded:
    """Tests when a component reports unhealthy status → HTTP 503."""

    @pytest.mark.asyncio
    async def test_returns_503_when_pipeline_stopped(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        app = create_health_app(state={"pipeline": "stopped", "storage": "connected"})
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.status == 503

    @pytest.mark.asyncio
    async def test_returns_degraded_status(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        app = create_health_app(state={"pipeline": "stopped", "storage": "connected"})
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_returns_503_when_storage_disconnected(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        app = create_health_app(state={"pipeline": "running", "storage": "disconnected"})
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.status == 503

    @pytest.mark.asyncio
    async def test_component_values_reflected_in_response(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        state = {"pipeline": "stopped", "storage": "error"}
        app = create_health_app(state=state)
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["components"]["pipeline"] == "stopped"
        assert body["components"]["storage"] == "error"


class TestCreateHealthApp:
    def test_creates_app_with_health_route(self) -> None:
        app = create_health_app()
        resources = [r.get_info().get("path", "") for r in app.router.resources()]
        assert "/api/v1/health" in resources

    def test_custom_state_injected(self) -> None:
        state = {"pipeline": "stopped"}
        app = create_health_app(state=state)
        assert app[_HEALTH_STATE_KEY] is state

    def test_default_state_is_healthy(self) -> None:
        app = create_health_app()
        assert app[_HEALTH_STATE_KEY]["pipeline"] == "running"
        assert app[_HEALTH_STATE_KEY]["storage"] == "connected"


class TestHealthWithDetection:
    """S-140: Health endpoint includes detection stats when ensemble is available."""

    @pytest.mark.asyncio
    async def test_includes_detection_when_ensemble_present(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import _ENSEMBLE_KEY, create_health_app, health_handler
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        app = create_health_app()
        app[_ENSEMBLE_KEY] = ensemble
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "detection" in body
        assert body["detection"]["source_count"] == 0

    @pytest.mark.asyncio
    async def test_omits_detection_when_no_ensemble(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import create_health_app, health_handler

        app = create_health_app()
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "detection" not in body

    @pytest.mark.asyncio
    async def test_detection_has_memory_estimate(self) -> None:
        import uuid

        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import _ENSEMBLE_KEY, create_health_app, health_handler
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models import SeerflowEvent, SeverityLevel

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="test",
            template_id=1,
            severity_id=SeverityLevel.INFORMATIONAL,
            source_type="syslog",
        )
        ensemble.process_event(event)
        app = create_health_app()
        app[_ENSEMBLE_KEY] = ensemble
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["detection"]["estimated_memory_bytes"] > 0


class TestHealthWithFeedbackStats:
    """S-050: Health endpoint includes feedback stats when storage is available."""

    @pytest.mark.asyncio
    async def test_includes_feedback_when_storage_present(self) -> None:
        from unittest.mock import AsyncMock

        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import _STORAGE_KEY, create_health_app, health_handler

        mock_storage = AsyncMock()
        mock_storage.get_feedback_stats.return_value = {"tp": 3, "fp": 1, "total": 4}
        app = create_health_app()
        app[_STORAGE_KEY] = mock_storage
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "feedback" in body
        assert body["feedback"] == {"tp": 3, "fp": 1, "total": 4}

    @pytest.mark.asyncio
    async def test_omits_feedback_when_no_storage(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import create_health_app, health_handler

        app = create_health_app()
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "feedback" not in body

    @pytest.mark.asyncio
    async def test_feedback_stats_with_zero_counts(self) -> None:
        from unittest.mock import AsyncMock

        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import _STORAGE_KEY, create_health_app, health_handler

        mock_storage = AsyncMock()
        mock_storage.get_feedback_stats.return_value = {"tp": 0, "fp": 0, "total": 0}
        app = create_health_app()
        app[_STORAGE_KEY] = mock_storage
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["feedback"] == {"tp": 0, "fp": 0, "total": 0}

    @pytest.mark.asyncio
    async def test_feedback_stats_called_once(self) -> None:
        from unittest.mock import AsyncMock

        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import _STORAGE_KEY, create_health_app, health_handler

        mock_storage = AsyncMock()
        mock_storage.get_feedback_stats.return_value = {"tp": 0, "fp": 0, "total": 0}
        app = create_health_app()
        app[_STORAGE_KEY] = mock_storage
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        await health_handler(request)
        mock_storage.get_feedback_stats.assert_awaited_once()
