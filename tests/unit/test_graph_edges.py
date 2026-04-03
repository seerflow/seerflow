"""Tests for entity graph edge inference."""

from __future__ import annotations

import uuid

from seerflow.graph.edges import EDGE_TYPE_MAP, EdgeRecord, infer_edges
from seerflow.models.event import SeerflowEvent


def _make_event(
    *,
    related_ips: tuple[str, ...] = (),
    related_users: tuple[str, ...] = (),
    related_hosts: tuple[str, ...] = (),
    related_files: tuple[str, ...] = (),
    related_domains: tuple[str, ...] = (),
    related_processes: tuple[str, ...] = (),
    entity_refs: tuple[str, ...] = (),
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        severity_id=6,
        message="test",
        source_type="syslog",
        related_ips=related_ips,
        related_users=related_users,
        related_hosts=related_hosts,
        related_files=related_files,
        related_domains=related_domains,
        related_processes=related_processes,
        entity_refs=entity_refs,
    )


class TestEdgeTypeMap:
    def test_has_seven_pairs(self) -> None:
        assert len(EDGE_TYPE_MAP) == 7

    def test_user_ip(self) -> None:
        assert EDGE_TYPE_MAP[("user", "ip")] == "authenticated_from"

    def test_user_host(self) -> None:
        assert EDGE_TYPE_MAP[("user", "host")] == "logged_into"

    def test_ip_host(self) -> None:
        assert EDGE_TYPE_MAP[("ip", "host")] == "has_ip"

    def test_user_file(self) -> None:
        assert EDGE_TYPE_MAP[("user", "file")] == "accessed"

    def test_process_process(self) -> None:
        assert EDGE_TYPE_MAP[("process", "process")] == "spawned_by"

    def test_ip_domain(self) -> None:
        assert EDGE_TYPE_MAP[("ip", "domain")] == "resolved_to"

    def test_host_ip(self) -> None:
        assert EDGE_TYPE_MAP[("host", "ip")] == "connected_to"


class TestInferEdges:
    def test_user_and_ip_produces_authenticated_from(self) -> None:
        from seerflow.models.entity import generate_ip_id, generate_user_id, normalize_username

        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        ip_uuid = str(generate_ip_id("10.0.1.1"))
        event = _make_event(
            related_ips=("10.0.1.1",),
            related_users=("admin",),
            entity_refs=(ip_uuid, user_uuid),
        )
        edges = infer_edges(event)
        assert len(edges) >= 1
        auth_edges = [e for e in edges if e.rel_type == "authenticated_from"]
        assert len(auth_edges) == 1
        assert auth_edges[0].source_id == user_uuid
        assert auth_edges[0].target_id == ip_uuid

    def test_ip_and_host_produces_has_ip(self) -> None:
        from seerflow.models.entity import generate_host_id, generate_ip_id

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        host_uuid = str(generate_host_id("web-01"))
        event = _make_event(
            related_ips=("10.0.1.1",),
            related_hosts=("web-01",),
            entity_refs=(ip_uuid, host_uuid),
        )
        edges = infer_edges(event)
        has_ip = [e for e in edges if e.rel_type == "has_ip"]
        assert len(has_ip) == 1

    def test_all_three_types_produces_four_edges(self) -> None:
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
        event = _make_event(
            related_ips=("10.0.1.1",),
            related_users=("admin",),
            related_hosts=("web-01",),
            entity_refs=(ip_uuid, user_uuid, host_uuid),
        )
        edges = infer_edges(event)
        # ip+host generates both has_ip (ip→host) and connected_to (host→ip)
        assert len(edges) == 4
        rel_types = {e.rel_type for e in edges}
        assert rel_types == {"authenticated_from", "logged_into", "has_ip", "connected_to"}

    def test_no_entities_returns_empty(self) -> None:
        event = _make_event()
        edges = infer_edges(event)
        assert edges == []

    def test_single_entity_type_returns_empty(self) -> None:
        from seerflow.models.entity import generate_ip_id

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        event = _make_event(related_ips=("10.0.1.1",), entity_refs=(ip_uuid,))
        edges = infer_edges(event)
        assert edges == []

    def test_multiple_ips_creates_edge_per_ip(self) -> None:
        from seerflow.models.entity import generate_ip_id, generate_user_id, normalize_username

        ip1 = str(generate_ip_id("10.0.1.1"))
        ip2 = str(generate_ip_id("10.0.1.2"))
        u, d = normalize_username("admin")
        user_uuid = str(generate_user_id(u, d))
        event = _make_event(
            related_ips=("10.0.1.1", "10.0.1.2"),
            related_users=("admin",),
            entity_refs=(ip1, ip2, user_uuid),
        )
        edges = infer_edges(event)
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
        event = _make_event(
            related_users=("admin",),
            related_files=("/etc/passwd",),
            entity_refs=(user_uuid, file_uuid),
        )
        edges = infer_edges(event)
        accessed = [e for e in edges if e.rel_type == "accessed"]
        assert len(accessed) == 1
        assert accessed[0].source_id == user_uuid
        assert accessed[0].target_id == file_uuid

    def test_ip_and_domain_produces_resolved_to(self) -> None:
        from seerflow.models.entity import generate_domain_id, generate_ip_id

        ip_uuid = str(generate_ip_id("10.0.1.1"))
        domain_uuid = str(generate_domain_id("evil.com"))
        event = _make_event(
            related_ips=("10.0.1.1",),
            related_domains=("evil.com",),
            entity_refs=(ip_uuid, domain_uuid),
        )
        edges = infer_edges(event)
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
        event = _make_event(
            related_ips=("10.0.1.1",),
            related_users=("admin",),
            related_hosts=("web-01",),
            related_domains=("example.com",),
            related_files=("/tmp/test",),
            entity_refs=(ip_uuid, user_uuid, host_uuid, domain_uuid, file_uuid),
        )
        edges = infer_edges(event)
        rel_types = {e.rel_type for e in edges}
        assert "authenticated_from" in rel_types
        assert "resolved_to" in rel_types
        assert "accessed" in rel_types
        assert len(edges) >= 6
