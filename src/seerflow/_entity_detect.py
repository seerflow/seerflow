"""Entity-shape detection for the CLI hunt path (S-076).

Given an arbitrary user string, decide whether it looks like a specific
observable (IP, host, user principal, UUID) we can resolve to a deterministic
entity UUID without an LLM round-trip. Free-form text returns ``None`` and
the caller falls through to natural-language hunting (S-072).

Module is intentionally pure: no I/O, no logging, no async. Used by
``seerflow.hunt_cmd`` today and re-exported for the Sprint 14 TUI's smart
search bar.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from typing import NamedTuple

from seerflow.models.entity import (
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    normalize_username,
)


class EntityHit(NamedTuple):
    """Result of a successful ``detect_entity`` match.

    Fields:
        entity_type: One of ``"ip"``, ``"host"``, ``"user"``, ``"uuid"``.
        entity_uuid: The resolved entity UUID as a string (UUID5 for IP /
            host / user; the original UUID itself for ``"uuid"``).
        entity_value: The original input value with surrounding whitespace
            stripped (preserved for display + logging).
    """

    entity_type: str
    entity_uuid: str
    entity_value: str


# A bare hostname must contain at least one dot AND each label must follow
# the LDH rule (letters, digits, hyphen; no leading/trailing hyphen, ≤ 63
# chars). Single-label hostnames are intentionally NOT matched — they're too
# easy to confuse with English words ("auth", "prod"). Operators wanting a
# single-label hunt can fall through to the NL path.
_HOST_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOST_RE = re.compile(rf"^{_HOST_LABEL}(\.{_HOST_LABEL})+$")

# A user principal needs either ``@`` or ``\`` to be recognisable; otherwise
# every free-form word would route as a user.
_USER_RE = re.compile(r"^[^\s@\\]+([@\\])[^\s]*$")


def _try_uuid(value: str) -> EntityHit | None:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    canonical = str(parsed)
    return EntityHit(entity_type="uuid", entity_uuid=canonical, entity_value=canonical)


def _try_ip(value: str) -> EntityHit | None:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return EntityHit(
        entity_type="ip",
        entity_uuid=str(generate_ip_id(value)),
        entity_value=value,
    )


def _try_user(value: str) -> EntityHit | None:
    if not _USER_RE.match(value):
        return None
    username, domain = normalize_username(value)
    if not username:
        return None
    return EntityHit(
        entity_type="user",
        entity_uuid=str(generate_user_id(username, domain)),
        entity_value=value,
    )


def _try_host(value: str) -> EntityHit | None:
    if not _HOST_RE.match(value):
        return None
    return EntityHit(
        entity_type="host",
        entity_uuid=str(generate_host_id(value)),
        entity_value=value,
    )


def detect_entity(value: str) -> EntityHit | None:
    """Detect whether ``value`` is a routable entity (IP/host/user/UUID).

    Returns an ``EntityHit`` on match, ``None`` for free-form text. Order
    matters: UUID → IP → user → host. A UUID-shaped string can never be a
    valid hostname (UUIDs contain dashes in fixed positions and exclusively
    hex characters), so the UUID check is safe to run first.
    """
    cleaned = value.strip() if value else ""
    if not cleaned:
        return None
    return _try_uuid(cleaned) or _try_ip(cleaned) or _try_user(cleaned) or _try_host(cleaned)


__all__ = ["EntityHit", "detect_entity"]
