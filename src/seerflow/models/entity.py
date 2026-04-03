"""Entity type definitions for the Seerflow entity graph.

Six frozen msgspec.Structs representing observable entities in log data.
Each struct uses ``tag_field="entity_type"`` for discriminated union decoding
via ``msgspec.json.decode(data, type=SecurityEntity)``.

Consumers should treat ``dict`` fields (``hashes``) as read-only.
"""

from __future__ import annotations

import ipaddress
import logging
import unicodedata
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
    username = unicodedata.normalize("NFC", username.strip())
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
    h = unicodedata.normalize("NFC", hostname.strip().lower().rstrip("."))
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


def _sanitize_for_log(value: str) -> str:
    """Strip control characters that enable log injection."""
    return value.replace("\n", "\\n").replace("\r", "\\r").replace("\x1b", "\\x1b")


def _parse_process_string(raw: str) -> tuple[str | None, int | None]:
    """Parse process extraction format into (name, pid) components.

    Formats: "name:pid" -> (name, pid), bare digits -> (None, pid), bare name -> (name, None).
    """
    if ":" in raw:
        parts = raw.rsplit(":", 1)
        try:
            return parts[0], int(parts[1])
        except (ValueError, IndexError):
            return raw, None
    if raw.isdigit():
        return None, int(raw)
    return raw, None


def _resolve_processes(raw_processes: tuple[str, ...]) -> list[str]:
    """Resolve process strings to UUID5 with cross-format dedup.

    Dedup rule: bare PIDs are dropped when a name:pid entry shares the same PID.
    """
    parsed: list[tuple[str, str | None, int | None]] = []
    for raw in raw_processes:
        name, pid = _parse_process_string(raw.strip())
        parsed.append((raw, name, pid))

    # Build set of PIDs that appear in name:pid entries
    named_pids: set[int] = set()
    for _raw, name, pid in parsed:
        if name is not None and pid is not None:
            named_pids.add(pid)

    resolved: list[str] = []
    seen: set[str] = set()
    for raw, name, pid in parsed:
        # Drop bare PIDs that are covered by a name:pid entry
        if name is None and pid is not None and pid in named_pids:
            continue

        try:
            if name is not None and pid is not None:
                uid = str(generate_process_id(hostname="", pid=pid, start_time=0))
            elif name is not None:
                uid = str(uuid.uuid5(NS_PROCESS, name))
            else:
                uid = str(uuid.uuid5(NS_PROCESS, str(pid)))

            if uid not in seen:
                seen.add(uid)
                resolved.append(uid)
        except (ValueError, TypeError):
            _log.warning("Skipping malformed process: %s", _sanitize_for_log(raw))

    return resolved


def resolve_entities(
    ips: tuple[str, ...],
    users: tuple[str, ...],
    hosts: tuple[str, ...],
    *,
    files: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
    processes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Resolve raw entity values to deterministic UUID5 strings.

    Calls the type-specific ``generate_*_id()`` for each value.
    Values that fail normalization (e.g. malformed IPs) are skipped
    with a warning log.  Returns a tuple of UUID5 string representations
    in priority order: IPs, users, hosts, domains, files, processes.
    """
    resolved: list[str] = []

    for raw_ip in ips:
        try:
            resolved.append(str(generate_ip_id(raw_ip)))
        except (ValueError, TypeError):
            _log.warning(
                "Skipping malformed IP: %s",
                _sanitize_for_log(raw_ip),
            )

    for raw_user in users:
        try:
            username, domain = normalize_username(raw_user)
            resolved.append(str(generate_user_id(username, domain)))
        except (ValueError, TypeError):
            _log.warning(
                "Skipping malformed user: %s",
                _sanitize_for_log(raw_user),
            )

    for raw_host in hosts:
        try:
            resolved.append(str(generate_host_id(raw_host)))
        except (ValueError, TypeError):
            _log.warning(
                "Skipping malformed host: %s",
                _sanitize_for_log(raw_host),
            )

    for raw_domain in domains:
        try:
            resolved.append(str(generate_domain_id(raw_domain)))
        except (ValueError, TypeError):
            _log.warning(
                "Skipping malformed domain: %s",
                _sanitize_for_log(raw_domain),
            )

    for raw_file in files:
        try:
            resolved.append(str(generate_file_id(raw_file)))
        except (ValueError, TypeError):
            _log.warning(
                "Skipping malformed file: %s",
                _sanitize_for_log(raw_file),
            )

    resolved.extend(_resolve_processes(processes))

    return tuple(resolved)


def primary_entity_value(event: SeerflowEvent) -> str:
    """Return the raw display value for the highest-priority entity.

    Priority: ip > user > host > domain > file > process.
    Returns ``""`` when no related fields are populated.
    Validates IPs before returning to stay in sync with resolve_entities().
    """
    if event.related_ips:
        try:
            ipaddress.ip_address(event.related_ips[0].strip())
            return event.related_ips[0]
        except ValueError:
            pass  # fall through to next type
    if event.related_users:
        return event.related_users[0]
    if event.related_hosts:
        return event.related_hosts[0]
    if event.related_domains:
        return event.related_domains[0]
    if event.related_files:
        return event.related_files[0]
    if event.related_processes:
        return event.related_processes[0]
    return ""


def infer_entity_type(event: SeerflowEvent) -> EntityType:
    """Infer the primary entity type from populated related_* fields.

    Priority: ip > user > host > domain > file > process.
    Falls back to ``"ip"`` when no related fields are populated.
    """
    if event.related_ips:
        return "ip"
    if event.related_users:
        return "user"
    if event.related_hosts:
        return "host"
    if event.related_domains:
        return "domain"
    if event.related_files:
        return "file"
    if event.related_processes:
        return "process"
    return "ip"
