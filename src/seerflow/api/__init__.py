"""REST API: FastAPI-based dashboard and health endpoints."""

from seerflow.api.app import create_api_app
from seerflow.api.health import create_health_app

__all__ = ["create_api_app", "create_health_app"]
