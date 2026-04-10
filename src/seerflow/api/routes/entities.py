"""GET /api/v1/entities/search -- entity search endpoint.

Falls back to LogStore.search_text when no EntityStore is configured,
extracting entity references from matching events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from seerflow.api.deps import StorageDeps, get_storage
from seerflow.api.schemas import EntitySearchResult

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent

router = APIRouter(tags=["entities"])

Storage = Annotated[StorageDeps, Depends(get_storage)]

_ENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("related_ips", "ip"),
    ("related_users", "user"),
    ("related_hosts", "host"),
    ("related_files", "file"),
    ("related_domains", "domain"),
    ("related_processes", "process"),
)


def _extract_entities(events: list[SeerflowEvent]) -> list[EntitySearchResult]:
    """Extract unique entity references from a list of events."""
    seen: set[tuple[str, str]] = set()
    results: list[EntitySearchResult] = []
    for event in events:
        for field_name, entity_type in _ENTITY_FIELDS:
            for value in getattr(event, field_name):
                key = (entity_type, value)
                if key not in seen:
                    seen.add(key)
                    results.append(EntitySearchResult(entity_type=entity_type, entity_value=value))
    return results


@router.get("/entities/search", response_model=list[EntitySearchResult])
async def search_entities(
    storage: Storage,
    q: str = Query(..., min_length=1, description="Search query"),
) -> list[EntitySearchResult]:
    """Search entities by value. Falls back to event text search."""
    events = await storage.log_store.search_text(q, limit=100)
    return _extract_entities(events)
