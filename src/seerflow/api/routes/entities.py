"""GET /api/v1/entities/search -- entity search endpoint.

Falls back to LogStore.search_text when no EntityStore is configured,
extracting entity references from matching events. Each result is stamped
with a deterministic UUID5 derived via the existing generate_*_id helpers.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from seerflow.api.deps import StorageDeps, get_storage
from seerflow.api.schemas import EntitySearchResult
from seerflow.models.entity import (
    generate_domain_id,
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    normalize_username,
)
from seerflow.models.query import EventQuery

if TYPE_CHECKING:
    from collections.abc import Callable

    from seerflow.models.event import SeerflowEvent

_log = logging.getLogger(__name__)

router = APIRouter(tags=["entities"])

Storage = Annotated[StorageDeps, Depends(get_storage)]


def _uuid_for_ip(value: str) -> str:
    return str(generate_ip_id(value))


def _uuid_for_user(value: str) -> str:
    username, domain = normalize_username(value)
    return str(generate_user_id(username, domain))


def _uuid_for_host(value: str) -> str:
    return str(generate_host_id(value))


def _uuid_for_domain(value: str) -> str:
    return str(generate_domain_id(value))


# Only the FR-036 pivot types carry UUIDs. Files/processes/hashes are shown in
# the timeline but are not search pivot targets.
_ENTITY_FIELDS: tuple[tuple[str, str, Callable[[str], str]], ...] = (
    ("related_ips", "ip", _uuid_for_ip),
    ("related_users", "user", _uuid_for_user),
    ("related_hosts", "host", _uuid_for_host),
    ("related_domains", "domain", _uuid_for_domain),
)


def _extract_entities(events: list[SeerflowEvent]) -> list[EntitySearchResult]:
    """Extract unique entity references from events, stamping UUIDs."""
    seen: set[tuple[str, str]] = set()
    results: list[EntitySearchResult] = []
    for event in events:
        for field_name, entity_type, resolver in _ENTITY_FIELDS:
            for value in getattr(event, field_name):
                key = (entity_type, value)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    entity_uuid = resolver(value)
                except (ValueError, TypeError):
                    _log.debug(
                        "Skipping malformed %s value in search: %r",
                        entity_type,
                        value,
                    )
                    continue
                results.append(
                    EntitySearchResult(
                        entity_type=entity_type,
                        entity_value=value,
                        entity_uuid=entity_uuid,
                    ),
                )
    return results


@router.get("/entities/search", response_model=list[EntitySearchResult])
async def search_entities(
    storage: Storage,
    q: str = Query(..., min_length=1, max_length=256, description="Search query"),
) -> list[EntitySearchResult]:
    """Search entities by value or UUID.

    UUID-shaped queries short-circuit to EventQuery(entity_uuid=...) and
    return only entities matching the queried UUID. Otherwise falls back
    to LogStore.search_text and extracts entity references from results.
    """
    try:
        parsed_uuid: _uuid_mod.UUID | None = _uuid_mod.UUID(q)
    except ValueError:
        parsed_uuid = None

    if parsed_uuid is not None:
        target = str(parsed_uuid)
        page = await storage.log_store.query_events(
            EventQuery(entity_uuid=target, limit=100),
        )
        all_entities = _extract_entities(list(page.items))
        return [r for r in all_entities if r.entity_uuid == target]

    events = await storage.log_store.search_text(q, limit=100)
    return _extract_entities(events)
