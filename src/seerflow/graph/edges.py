"""Edge inference from typed entity pairs."""

from __future__ import annotations

from dataclasses import dataclass

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


def infer_edges(typed_entities: list[tuple[str, str]]) -> list[EdgeRecord]:
    """Infer typed edges from pre-resolved (type, uuid) pairs.

    Uses the entity type pair mapping to determine relationship types.
    Process-process pairs produce a ``spawned_by`` edge (inline special case,
    not in EDGE_TYPE_MAP, since the map only handles cross-type pairs).
    Returns one edge per known (source_type, target_type) combination.

    **Limitation:** ``spawned_by`` direction is determined by extraction order
    (first process is source), not by parent-child semantics. With N > 2
    processes, N*(N-1)/2 edges are created — a full mesh, not a tree.

    Args:
        typed_entities: List of ``(entity_type, uuid_str)`` tuples, already
            resolved by the caller.  Types should be one of: ``ip``, ``user``,
            ``host``, ``domain``, ``file``, ``process``.
    """
    edges: list[EdgeRecord] = []
    for i, (type_a, uuid_a) in enumerate(typed_entities):
        for type_b, uuid_b in typed_entities[i + 1 :]:
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
