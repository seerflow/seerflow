"""Tests for entity graph edge inference."""

from __future__ import annotations

from seerflow.graph.edges import EDGE_TYPE_MAP, EdgeRecord, infer_edges


class TestEdgeTypeMap:
    def test_has_five_pairs(self) -> None:
        assert len(EDGE_TYPE_MAP) == 5

    def test_user_ip(self) -> None:
        assert EDGE_TYPE_MAP[("user", "ip")] == "authenticated_from"

    def test_user_host(self) -> None:
        assert EDGE_TYPE_MAP[("user", "host")] == "logged_into"

    def test_ip_host(self) -> None:
        assert EDGE_TYPE_MAP[("ip", "host")] == "has_ip"

    def test_user_file(self) -> None:
        assert EDGE_TYPE_MAP[("user", "file")] == "accessed"

    def test_ip_domain(self) -> None:
        assert EDGE_TYPE_MAP[("ip", "domain")] == "resolved_to"


class TestInferEdges:
    def test_user_and_ip_produces_authenticated_from(self) -> None:
        from seerflow.models.entity import generate_ip_id, generate_user_id, normalize_username

        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        ip_uuid = str(generate_ip_id("10.0.1.1"))
        typed = [("ip", ip_uuid), ("user", user_uuid)]
        edges = infer_edges(typed_entities=typed)
        assert len(edges) >= 1
        auth_edges = [e for e in edges if e.rel_type == "authenticated_from"]
        assert len(auth_edges) == 1
        assert auth_edges[0].source_id == user_uuid
        assert auth_edges[0].target_id == ip_uuid

    def test_ip_and_host_produces_has_ip(self) -> None:
        from seerflow.models.entity import generate_host_id, generate_ip_id

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        host_uuid = str(generate_host_id("web-01"))
        typed = [("ip", ip_uuid), ("host", host_uuid)]
        edges = infer_edges(typed_entities=typed)
        has_ip = [e for e in edges if e.rel_type == "has_ip"]
        assert len(has_ip) == 1

    def test_all_three_types_produces_three_edges(self) -> None:
        from seerflow.models.entity import (
            generate_host_id,
            generate_ip_id,
            generate_user_id,
            normalize_username,
        )

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        host_uuid = str(generate_host_id("web-01"))
        typed = [("ip", ip_uuid), ("user", user_uuid), ("host", host_uuid)]
        edges = infer_edges(typed_entities=typed)
        assert len(edges) == 3
        rel_types = {e.rel_type for e in edges}
        assert rel_types == {"authenticated_from", "logged_into", "has_ip"}

    def test_no_entities_returns_empty(self) -> None:
        edges = infer_edges(typed_entities=[])
        assert edges == []

    def test_single_entity_type_returns_empty(self) -> None:
        from seerflow.models.entity import generate_ip_id

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        edges = infer_edges(typed_entities=[("ip", ip_uuid)])
        assert edges == []

    def test_multiple_ips_creates_edge_per_ip(self) -> None:
        from seerflow.models.entity import generate_ip_id, generate_user_id, normalize_username

        ip1 = str(generate_ip_id("10.0.1.1"))
        ip2 = str(generate_ip_id("10.0.1.2"))
        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        typed = [("ip", ip1), ("ip", ip2), ("user", user_uuid)]
        edges = infer_edges(typed_entities=typed)
        auth_edges = [e for e in edges if e.rel_type == "authenticated_from"]
        assert len(auth_edges) == 2

    def test_edge_record_is_frozen(self) -> None:
        import pytest

        edge = EdgeRecord(source_id="a", target_id="b", rel_type="has_ip")
        with pytest.raises(AttributeError):
            edge.source_id = "c"  # type: ignore[misc]


class TestInferEdgesExtended:
    def test_user_and_file_produces_accessed(self) -> None:
        from seerflow.models.entity import generate_file_id, generate_user_id, normalize_username

        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        file_uuid = str(generate_file_id("/etc/passwd"))
        typed = [("user", user_uuid), ("file", file_uuid)]
        edges = infer_edges(typed_entities=typed)
        accessed = [e for e in edges if e.rel_type == "accessed"]
        assert len(accessed) == 1
        assert accessed[0].source_id == user_uuid
        assert accessed[0].target_id == file_uuid

    def test_ip_and_domain_produces_resolved_to(self) -> None:
        from seerflow.models.entity import generate_domain_id, generate_ip_id

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        domain_uuid = str(generate_domain_id("evil.com"))
        typed = [("ip", ip_uuid), ("domain", domain_uuid)]
        edges = infer_edges(typed_entities=typed)
        resolved = [e for e in edges if e.rel_type == "resolved_to"]
        assert len(resolved) == 1
        assert resolved[0].source_id == ip_uuid
        assert resolved[0].target_id == domain_uuid

    def test_six_types_produces_multiple_edges(self) -> None:
        from seerflow.models.entity import (
            generate_domain_id,
            generate_file_id,
            generate_host_id,
            generate_ip_id,
            generate_user_id,
            normalize_username,
        )

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        host_uuid = str(generate_host_id("web-01"))
        domain_uuid = str(generate_domain_id("example.com"))
        file_uuid = str(generate_file_id("/tmp/test"))
        typed = [
            ("ip", ip_uuid),
            ("user", user_uuid),
            ("host", host_uuid),
            ("domain", domain_uuid),
            ("file", file_uuid),
        ]
        edges = infer_edges(typed_entities=typed)
        rel_types = {e.rel_type for e in edges}
        assert "authenticated_from" in rel_types
        assert "resolved_to" in rel_types
        assert "accessed" in rel_types
        assert len(edges) >= 5

    def test_two_processes_produces_spawned_by(self) -> None:
        import uuid as _uuid

        from seerflow.models.entity import NS_PROCESS

        proc1_uuid = str(_uuid.uuid5(NS_PROCESS, "sshd:1234"))
        proc2_uuid = str(_uuid.uuid5(NS_PROCESS, "bash:5678"))
        typed = [("process", proc1_uuid), ("process", proc2_uuid)]
        edges = infer_edges(typed_entities=typed)
        spawned = [e for e in edges if e.rel_type == "spawned_by"]
        assert len(spawned) == 1
        assert spawned[0].source_id == proc1_uuid
        assert spawned[0].target_id == proc2_uuid

    def test_three_processes_produce_full_mesh(self) -> None:
        """Three process entities produce 3 spawned_by edges (full mesh)."""
        entities = [("process", "uuid-p1"), ("process", "uuid-p2"), ("process", "uuid-p3")]
        edges = infer_edges(entities)
        spawned = [e for e in edges if e.rel_type == "spawned_by"]
        assert len(spawned) == 3
        pairs = {(e.source_id, e.target_id) for e in spawned}
        assert ("uuid-p1", "uuid-p2") in pairs
        assert ("uuid-p1", "uuid-p3") in pairs
        assert ("uuid-p2", "uuid-p3") in pairs


class TestInferEdgesTypedInput:
    """Tests for infer_edges with pre-resolved typed entity list."""

    def test_accepts_typed_entities(self) -> None:
        from seerflow.models.entity import generate_ip_id, generate_user_id, normalize_username

        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        ip_uuid = str(generate_ip_id("10.0.1.1"))
        typed = [("ip", ip_uuid), ("user", user_uuid)]
        edges = infer_edges(typed_entities=typed)
        auth = [e for e in edges if e.rel_type == "authenticated_from"]
        assert len(auth) == 1

    def test_empty_list_returns_empty(self) -> None:
        edges = infer_edges(typed_entities=[])
        assert edges == []
