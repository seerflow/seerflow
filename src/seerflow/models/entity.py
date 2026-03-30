"""Entity type definitions for the Seerflow entity graph.

Six frozen msgspec.Structs representing observable entities in log data.
Each struct uses ``tag_field="entity_type"`` for discriminated union decoding
via ``msgspec.json.decode(data, type=SecurityEntity)``.

Consumers should treat ``dict`` fields (``hashes``) as read-only.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.models._types import EntityType
    from seerflow.models.event import SeerflowEvent

import msgspec

# ---------------------------------------------------------------------------
# UUID5 namespace constants (one per entity type)
# ---------------------------------------------------------------------------

NS_USER = uuid.UUID("a1b2c3d4-0001-0000-0000-000000000001")
NS_IP = uuid.UUID("a1b2c3d4-0002-0000-0000-000000000002")
NS_HOST = uuid.UUID("a1b2c3d4-0003-0000-0000-000000000003")
NS_PROCESS = uuid.UUID("a1b2c3d4-0004-0000-0000-000000000004")
NS_FILE = uuid.UUID("a1b2c3d4-0005-0000-0000-000000000005")
NS_DOMAIN = uuid.UUID("a1b2c3d4-0006-0000-0000-000000000006")

_log = logging.getLogger("seerflow")


# ---------------------------------------------------------------------------
# Entity structs
# ---------------------------------------------------------------------------


class UserEntity(msgspec.Struct, frozen=True, tag_field="entity_type", tag="user"):
    """A user identity observed in log data."""

    entity_id: uuid.UUID
    first_seen: int
    last_seen: int
    username: str
    domain: str | None = None
    email: str | None = None
    sid: str | None = None
    uid: int | None = None
    groups: tuple[str, ...] = ()
    is_service_account: bool = False
    source_count: int = 1
    confidence: float = 1.0


class IPEntity(msgspec.Struct, frozen=True, tag_field="entity_type", tag="ip"):
    """An IP address observed in log data."""

    entity_id: uuid.UUID
    first_seen: int
    last_seen: int
    address: str
    version: int = 4
    is_private: bool = False
    is_tor_exit: bool = False
    asn: int | None = None
    asn_org: str | None = None
    geo_country: str | None = None
    geo_city: str | None = None


class HostEntity(msgspec.Struct, frozen=True, tag_field="entity_type", tag="host"):
    """A host (machine) observed in log data."""

    entity_id: uuid.UUID
    first_seen: int
    last_seen: int
    hostname: str
    fqdn: str | None = None
    os_family: str | None = None
    ip_addresses: tuple[str, ...] = ()
    mac_addresses: tuple[str, ...] = ()


class ProcessEntity(msgspec.Struct, frozen=True, tag_field="entity_type", tag="process"):
    """A process observed in log data."""

    entity_id: uuid.UUID
    first_seen: int
    last_seen: int
    pid: int
    name: str
    command_line: str | None = None
    image_path: str | None = None
    hashes: dict[str, str] = msgspec.field(default_factory=dict)
    parent_pid: int | None = None
    user: str | None = None
    host: str | None = None
    creation_time: int | None = None


class FileEntity(msgspec.Struct, frozen=True, tag_field="entity_type", tag="file"):
    """A file observed in log data."""

    entity_id: uuid.UUID
    first_seen: int
    last_seen: int
    path: str
    name: str = ""
    hashes: dict[str, str] = msgspec.field(default_factory=dict)
    size: int | None = None
    owner: str | None = None


class DomainEntity(msgspec.Struct, frozen=True, tag_field="entity_type", tag="domain"):
    """A domain name observed in log data."""

    entity_id: uuid.UUID
    first_seen: int
    last_seen: int
    domain: str
    registrar: str | None = None
    creation_date: int | None = None
    is_dga: bool = False


SecurityEntity = UserEntity | IPEntity | HostEntity | ProcessEntity | FileEntity | DomainEntity


# ---------------------------------------------------------------------------
# Username normalization
# ---------------------------------------------------------------------------


def normalize_username(raw: str, default_domain: str = "") -> tuple[str, str]:
    """Normalize username: strip domain prefix, lowercase.

    Handles ``DOMAIN\\user`` and ``user@domain`` formats.
    Returns ``(username, domain)`` tuple, both lowercased.
    """
    raw = raw.strip()
    if "\\" in raw:
        domain, username = raw.split("\\", 1)
        return username.lower(), domain.lower()
    if "@" in raw:
        username, domain = raw.rsplit("@", 1)
        return username.lower(), domain.lower()
    return raw.lower(), default_domain.lower()


# ---------------------------------------------------------------------------
# UUID5 identity generators
# ---------------------------------------------------------------------------


def generate_user_id(username: str, domain: str) -> uuid.UUID:
    """Deterministic UUID5 for a user entity."""
    username = username.strip()
    if not username:
        msg = "username is empty"
        raise ValueError(msg)
    canonical = f"{domain}:{username}" if domain else username
    return uuid.uuid5(NS_USER, canonical)


def generate_ip_id(raw: str) -> uuid.UUID:
    """Deterministic UUID5 for an IP entity."""
    addr = ipaddress.ip_address(raw.strip())
    normalized = addr.exploded if isinstance(addr, ipaddress.IPv6Address) else str(addr)
    return uuid.uuid5(NS_IP, normalized)


def generate_host_id(hostname: str, domain: str = "") -> uuid.UUID:
    """Deterministic UUID5 for a host entity."""
    h = hostname.strip().lower().rstrip(".")
    if not h:
        msg = "hostname is empty"
        raise ValueError(msg)
    canonical = f"{h}.{domain}" if domain and "." not in h else h
    return uuid.uuid5(NS_HOST, canonical)


def generate_process_id(hostname: str, pid: int, start_time: int) -> uuid.UUID:
    """Deterministic UUID5 for a process entity."""
    if pid < 0:
        msg = f"pid must be >= 0, got {pid}"
        raise ValueError(msg)
    return uuid.uuid5(NS_PROCESS, f"{hostname}:{pid}:{start_time}")


def generate_file_id(path: str) -> uuid.UUID:
    """Deterministic UUID5 for a file entity."""
    canonical = path.strip()
    if not canonical:
        msg = "file path is empty"
        raise ValueError(msg)
    return uuid.uuid5(NS_FILE, canonical)


def generate_domain_id(domain: str) -> uuid.UUID:
    """Deterministic UUID5 for a domain entity."""
    canonical = domain.strip().lower().rstrip(".")
    if not canonical:
        msg = "domain is empty"
        raise ValueError(msg)
    return uuid.uuid5(NS_DOMAIN, canonical)


# ---------------------------------------------------------------------------
# Batch entity resolution
# ---------------------------------------------------------------------------


def resolve_entities(
    ips: tuple[str, ...],
    users: tuple[str, ...],
    hosts: tuple[str, ...],
) -> tuple[str, ...]:
    """Resolve raw entity values to deterministic UUID5 strings.

    Calls the type-specific ``generate_*_id()`` for each value.
    Values that fail normalization (e.g. malformed IPs) are skipped
    with a warning log.  Returns a tuple of UUID5 string representations
    in order: IPs, then users, then hosts.
    """
    resolved: list[str] = []

    for raw_ip in ips:
        try:
            resolved.append(str(generate_ip_id(raw_ip)))
        except (ValueError, TypeError):
            _log.warning("Skipping malformed IP during entity resolution: %s", raw_ip)

    for raw_user in users:
        try:
            username, domain = normalize_username(raw_user)
            resolved.append(str(generate_user_id(username, domain)))
        except (ValueError, TypeError):
            _log.warning("Skipping malformed user during entity resolution: %s", raw_user)

    for raw_host in hosts:
        try:
            resolved.append(str(generate_host_id(raw_host)))
        except (ValueError, TypeError):
            _log.warning("Skipping malformed host during entity resolution: %s", raw_host)

    return tuple(resolved)


def infer_entity_type(event: SeerflowEvent) -> EntityType:
    """Infer the primary entity type from populated related_* fields.

    Priority: ip > user > host.  Falls back to ``"ip"`` when no
    related fields are populated (matches current default behaviour).
    """
    if event.related_ips:
        return "ip"
    if event.related_users:
        return "user"
    if event.related_hosts:
        return "host"
    return "ip"
