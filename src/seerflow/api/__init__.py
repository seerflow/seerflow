"""REST API and WebSocket: FastAPI dashboard backend."""

from seerflow.api.health import create_health_app, health_handler

__all__ = ["create_health_app", "health_handler"]
