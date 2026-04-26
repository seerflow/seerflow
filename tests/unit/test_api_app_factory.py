"""Tests for ``seerflow.api.app.create_api_app`` factory keyword surface (S-217)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from seerflow.api.app import create_api_app


def _stub_alert_store() -> MagicMock:
    store = MagicMock()
    store.get_feedback_stats = AsyncMock(return_value={"tp": 0, "fp": 0})
    return store


class TestCreateApiAppHealthState:
    """``health_state`` kwarg lets the pipeline share its mutable status dict."""

    def test_passing_health_state_dict_is_stored_on_app_state(self) -> None:
        shared: dict[str, str] = {"pipeline": "running", "storage": "connected"}
        app = create_api_app(
            log_store=MagicMock(),
            alert_store=_stub_alert_store(),
            health_state=shared,
        )
        assert app.state.health_state is shared  # identity, not copy

    def test_omitting_health_state_creates_default(self) -> None:
        app = create_api_app(log_store=MagicMock(), alert_store=_stub_alert_store())
        assert app.state.health_state == {
            "pipeline": "running",
            "storage": "connected",
        }


class TestCreateApiAppEnsemble:
    """``ensemble`` kwarg propagates into ``DetectionEngines``."""

    def test_ensemble_threaded_into_engines(self) -> None:
        ensemble = MagicMock()
        app = create_api_app(
            log_store=MagicMock(),
            alert_store=_stub_alert_store(),
            ensemble=ensemble,
        )
        assert app.state.engines.ensemble is ensemble

    def test_ensemble_defaults_to_none(self) -> None:
        app = create_api_app(log_store=MagicMock(), alert_store=_stub_alert_store())
        assert app.state.engines.ensemble is None
