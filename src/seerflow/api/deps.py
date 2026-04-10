"""Dependency injection for the FastAPI API layer.

StorageDeps bundles storage Protocol instances. Depends providers extract
them from FastAPI app.state so route handlers stay decoupled from wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

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


_MAX_TIMESTAMP_NS = 2**63 - 1  # SQLite int64 ceiling (~year 2262)


def parse_timestamp_ns(iso_str: str) -> int:
    """Convert an ISO-8601 string to nanoseconds since epoch.

    Assumes UTC if no timezone info is present.
    Raises ValueError if the result is out of int64 range.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    ns = int(dt.timestamp() * 1_000_000_000)
    if ns < 0 or ns > _MAX_TIMESTAMP_NS:
        msg = f"Timestamp out of supported range: {iso_str!r}"
        raise ValueError(msg)
    return ns


def require_entity_store(storage: StorageDeps) -> EntityStore:
    """FastAPI Depends -- return entity_store or 503 if missing."""
    if storage.entity_store is None:
        raise HTTPException(
            status_code=503,
            detail="entity_store not configured",
        )
    return storage.entity_store
