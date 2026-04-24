"""Regression tests for the single-tenant, single-Limiter-per-process contract (S-185).

The slowapi ``Limiter`` is a module-level singleton; ``configure_limiter``
mutates its internals per app. These tests pin that behaviour in code so
a future attempt at multi-app-per-process runs gets a loud, locatable
failure rather than silent counter bleed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import SeerflowConfig

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


def _build(backend: SqliteBackend, **overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_rate_limit_enabled": True,
        "api_list_rate_limit": "2/minute",
        "api_detail_rate_limit": "100/minute",
        "api_coverage_rate_limit": "2/minute",
        "api_allowed_origins": ("http://localhost:3000",),
    }
    defaults.update(overrides)
    cfg = SeerflowConfig(**defaults)  # type: ignore[arg-type]
    app = create_api_app(log_store=backend, alert_store=backend, config=cfg)
    return TestClient(app)


class TestParallelApps:
    """Codify the single-tenant contract documented in seerflow.api.limits."""

    async def test_second_app_config_wins_for_subsequent_requests(
        self, backend: SqliteBackend
    ) -> None:
        """Second configure_limiter call wins: app_b's limit governs app_b requests."""
        _app_a = _build(backend, api_list_rate_limit="100/minute")
        app_b = _build(backend, api_list_rate_limit="1/minute")

        r1 = app_b.get("/api/v1/alerts")
        r2 = app_b.get("/api/v1/alerts")
        assert r1.status_code == 200
        assert r2.status_code == 429, (
            "Second app reconfigured limit to 1/minute; second request must be 429"
        )

    async def test_reconfigure_resets_counters(self, backend: SqliteBackend) -> None:
        """Rebuilding the limiter for a new app clears in-memory counters."""
        app_a = _build(backend, api_list_rate_limit="2/minute")
        for _ in range(2):
            assert app_a.get("/api/v1/alerts").status_code == 200
        assert app_a.get("/api/v1/alerts").status_code == 429

        app_b = _build(backend, api_list_rate_limit="2/minute")
        assert app_b.get("/api/v1/alerts").status_code == 200, (
            "Fresh app must start with a clean bucket; storage rebind is broken"
        )

    async def test_reconfigure_to_disabled_actually_disables_enforcement(
        self, backend: SqliteBackend
    ) -> None:
        """enabled=False on the second app disables enforcement for that app."""
        _app_a = _build(backend, api_rate_limit_enabled=True, api_list_rate_limit="1/minute")
        app_b = _build(backend, api_rate_limit_enabled=False, api_list_rate_limit="1/minute")

        for _ in range(5):
            r = app_b.get("/api/v1/alerts")
            assert r.status_code == 200, (
                "enabled=False on second app must disable enforcement; "
                "singleton mutation leaked stale enabled=True"
            )
