"""REST API: aiohttp-based health and dashboard endpoints."""

from seerflow.api.health import create_health_app

__all__ = ["create_health_app"]
