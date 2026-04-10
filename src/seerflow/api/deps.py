"""Dependency injection for the FastAPI API layer.

StorageDeps bundles storage Protocol instances. Depends providers extract
them from FastAPI app.state so route handlers stay decoupled from wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import Request  # noqa: TC002 - runtime dep for FastAPI DI

if TYPE_CHECKING:
    from seerflow.storage.protocols import AlertStore, EntityStore, LogStore


@dataclass(frozen=True, slots=True)
class StorageDeps:
    """Bundle of storage backends injected into the FastAPI app."""

    log_store: LogStore
    alert_store: AlertStore
    entity_store: EntityStore | None = None


def get_storage(request: Request) -> StorageDeps:
    """FastAPI Depends provider -- retrieves StorageDeps from app.state."""
    return request.app.state.storage  # type: ignore[no-any-return]


def get_health_state(request: Request) -> dict[str, str]:
    """FastAPI Depends provider -- retrieves mutable health state dict."""
    return request.app.state.health_state  # type: ignore[no-any-return]


def parse_timestamp_ns(iso_str: str) -> int:
    """Convert an ISO-8601 string to nanoseconds since epoch.

    Assumes UTC if no timezone info is present.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)
