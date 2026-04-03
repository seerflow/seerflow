"""Edge inference from SeerflowEvent entity pairs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from seerflow.models.entity import resolve_entities

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent

EDGE_TYPE_MAP: dict[tuple[str, str], str] = {
    ("user", "ip"): "authenticated_from",
    ("user", "host"): "logged_into",
    ("ip", "host"): "has_ip",
    ("user", "file"): "accessed",
    ("ip", "domain"): "resolved_to",
}


@dataclass(frozen=True, slots=True)
class EdgeRecord:
    """A typed, directed edge between two entities."""

    source_id: str
    target_id: str
    rel_type: str


def infer_edges(event: SeerflowEvent) -> list[EdgeRecord]:
    """Infer typed edges from entity pairs in an event.

    Uses the entity type pair mapping to determine relationship types.
    Process-process pairs produce a ``spawned_by`` edge (inline special case,
    not in EDGE_TYPE_MAP, since the map only handles cross-type pairs).
    Returns one edge per known (source_type, target_type) combination.
    """
    typed: list[tuple[str, str]] = []
    ip_uuids = resolve_entities(event.related_ips, (), ())
    user_uuids = resolve_entities((), event.related_users, ())
    host_uuids = resolve_entities((), (), event.related_hosts)
    domain_uuids = resolve_entities((), (), (), domains=event.related_domains)
    file_uuids = resolve_entities((), (), (), files=event.related_files)
    process_uuids = resolve_entities((), (), (), processes=event.related_processes)

    for ip_uuid in ip_uuids:
        typed.append(("ip", ip_uuid))
    for user_uuid in user_uuids:
        typed.append(("user", user_uuid))
    for host_uuid in host_uuids:
        typed.append(("host", host_uuid))
    for domain_uuid in domain_uuids:
        typed.append(("domain", domain_uuid))
    for file_uuid in file_uuids:
        typed.append(("file", file_uuid))
    for process_uuid in process_uuids:
        typed.append(("process", process_uuid))

    edges: list[EdgeRecord] = []
    for i, (type_a, uuid_a) in enumerate(typed):
        for type_b, uuid_b in typed[i + 1 :]:
            if type_a == type_b:
                # Special case: process→process spawned_by
                if type_a == "process":
                    edges.append(
                        EdgeRecord(source_id=uuid_a, target_id=uuid_b, rel_type="spawned_by")
                    )
                continue
            rel = EDGE_TYPE_MAP.get((type_a, type_b))
            if rel is not None:
                edges.append(EdgeRecord(source_id=uuid_a, target_id=uuid_b, rel_type=rel))
                continue
            rel = EDGE_TYPE_MAP.get((type_b, type_a))
            if rel is not None:
                edges.append(EdgeRecord(source_id=uuid_b, target_id=uuid_a, rel_type=rel))

    return edges
