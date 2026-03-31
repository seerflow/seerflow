"""Tests for UUID5 entity resolution."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from seerflow.models.entity import (
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    infer_entity_type,
    normalize_username,
    resolve_entities,
)
from seerflow.models.event import SeerflowEvent


class TestResolveEntities:
    """Tests for resolve_entities()."""

    def test_ip_resolved_to_uuid5(self) -> None:
        result = resolve_entities(ips=("10.0.1.42",), users=(), hosts=())
        assert len(result) == 1
        parsed = uuid.UUID(result[0])
        assert parsed.version == 5
        assert result[0] == str(generate_ip_id("10.0.1.42"))

    def test_user_resolved_to_uuid5(self) -> None:
        result = resolve_entities(ips=(), users=("admin",), hosts=())
        assert len(result) == 1
        parsed = uuid.UUID(result[0])
        assert parsed.version == 5
        username, domain = normalize_username("admin")
        assert result[0] == str(generate_user_id(username, domain))

    def test_host_resolved_to_uuid5(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=("web-01",))
        assert len(result) == 1
        parsed = uuid.UUID(result[0])
        assert parsed.version == 5
        assert result[0] == str(generate_host_id("web-01"))

    def test_same_ip_produces_same_uuid5(self) -> None:
        r1 = resolve_entities(ips=("10.0.1.42",), users=(), hosts=())
        r2 = resolve_entities(ips=("10.0.1.42",), users=(), hosts=())
        assert r1 == r2

    def test_same_username_different_formats_same_uuid5(self) -> None:
        r1 = resolve_entities(ips=(), users=("admin",), hosts=())
        r2 = resolve_entities(ips=(), users=("ADMIN",), hosts=())
        assert r1 == r2

    def test_same_host_case_insensitive(self) -> None:
        r1 = resolve_entities(ips=(), users=(), hosts=("WEB-01",))
        r2 = resolve_entities(ips=(), users=(), hosts=("web-01",))
        assert r1 == r2

    def test_different_types_same_value_no_collision(self) -> None:
        ip_result = resolve_entities(ips=("10.0.1.1",), users=(), hosts=())
        host_result = resolve_entities(ips=(), users=(), hosts=("10.0.1.1",))
        assert ip_result[0] != host_result[0]

    def test_empty_inputs_returns_empty(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=())
        assert result == ()

    def test_multiple_entities_all_resolved(self) -> None:
        result = resolve_entities(
            ips=("10.0.1.1", "10.0.1.2"),
            users=("admin",),
            hosts=("web-01",),
        )
        assert len(result) == 4
        for r in result:
            parsed = uuid.UUID(r)
            assert parsed.version == 5

    def test_malformed_ip_skipped_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            result = resolve_entities(ips=("not-an-ip",), users=(), hosts=())
        assert len(result) == 0
        assert "not-an-ip" in caplog.text

    def test_malformed_user_skipped_with_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            result = resolve_entities(ips=(), users=("",), hosts=())
        assert len(result) == 0
        assert caplog.text

    def test_malformed_host_skipped_with_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            result = resolve_entities(ips=(), users=(), hosts=("",))
        assert len(result) == 0
        assert caplog.text

    def test_order_is_ips_then_users_then_hosts(self) -> None:
        result = resolve_entities(
            ips=("10.0.1.1",),
            users=("admin",),
            hosts=("web-01",),
        )
        assert result[0] == str(generate_ip_id("10.0.1.1"))
        username, domain = normalize_username("admin")
        assert result[1] == str(generate_user_id(username, domain))
        assert result[2] == str(generate_host_id("web-01"))


class TestInferEntityType:
    """Tests for infer_entity_type()."""

    def _make_event(
        self,
        *,
        related_ips: tuple[str, ...] = (),
        related_users: tuple[str, ...] = (),
        related_hosts: tuple[str, ...] = (),
    ) -> SeerflowEvent:
        import uuid as _uuid

        return SeerflowEvent(
            event_id=_uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            severity_id=6,
            message="test",
            source_type="syslog",
            related_ips=related_ips,
            related_users=related_users,
            related_hosts=related_hosts,
        )

    def test_ip_priority(self) -> None:
        event = self._make_event(related_ips=("10.0.1.1",), related_users=("admin",))
        assert infer_entity_type(event) == "ip"

    def test_user_when_no_ips(self) -> None:
        event = self._make_event(related_users=("admin",), related_hosts=("web-01",))
        assert infer_entity_type(event) == "user"

    def test_host_when_no_ips_or_users(self) -> None:
        event = self._make_event(related_hosts=("web-01",))
        assert infer_entity_type(event) == "host"

    def test_fallback_ip_when_nothing(self) -> None:
        event = self._make_event()
        assert infer_entity_type(event) == "ip"
