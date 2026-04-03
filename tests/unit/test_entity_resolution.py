"""Tests for UUID5 entity resolution."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from seerflow.models.entity import (
    generate_domain_id,
    generate_file_id,
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    infer_entity_type,
    normalize_username,
    primary_entity_value,
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


class TestResolveEntitiesExtended:
    """Tests for file/domain/process resolution in resolve_entities()."""

    def test_domain_resolved_to_uuid5(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=(), domains=("evil.com",))
        assert len(result) == 1
        assert result[0] == str(generate_domain_id("evil.com"))

    def test_file_resolved_to_uuid5(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=(), files=("/etc/passwd",))
        assert len(result) == 1
        assert result[0] == str(generate_file_id("/etc/passwd"))

    def test_process_name_pid_resolved(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=(), processes=("sshd:1234",))
        assert len(result) == 1
        parsed = uuid.UUID(result[0])
        assert parsed.version == 5

    def test_process_dedup_bare_pid_dropped_when_name_pid_exists(self) -> None:
        result_both = resolve_entities(
            ips=(),
            users=(),
            hosts=(),
            processes=("sshd:1234", "1234"),
        )
        result_named = resolve_entities(
            ips=(),
            users=(),
            hosts=(),
            processes=("sshd:1234",),
        )
        assert result_both == result_named

    def test_process_bare_pid_kept_when_no_name_pid(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=(), processes=("5678",))
        assert len(result) == 1

    def test_process_bare_name_kept(self) -> None:
        result = resolve_entities(ips=(), users=(), hosts=(), processes=("nginx",))
        assert len(result) == 1

    def test_six_type_order_is_ip_user_host_domain_file_process(self) -> None:
        result = resolve_entities(
            ips=("10.0.1.1",),
            users=("admin",),
            hosts=("web-01",),
            domains=("example.com",),
            files=("/tmp/test",),
            processes=("sshd:22",),
        )
        assert len(result) == 6
        assert result[0] == str(generate_ip_id("10.0.1.1"))
        assert result[3] == str(generate_domain_id("example.com"))
        assert result[4] == str(generate_file_id("/tmp/test"))

    def test_malformed_domain_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            result = resolve_entities(ips=(), users=(), hosts=(), domains=("",))
        assert len(result) == 0

    def test_malformed_file_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            result = resolve_entities(ips=(), users=(), hosts=(), files=("",))
        assert len(result) == 0

    def test_process_colon_only_resolves_as_name(self) -> None:
        """A bare ':' is treated as a name (no valid pid), producing a UUID."""
        result = resolve_entities(ips=(), users=(), hosts=(), processes=(":",))
        assert len(result) == 1  # uuid5(NS_PROCESS, ":") is valid

    def test_backward_compat_no_kwargs(self) -> None:
        """Existing callers passing only ips/users/hosts still work."""
        result = resolve_entities(("10.0.1.1",), ("admin",), ("web-01",))
        assert len(result) == 3


class TestNFCNormalization:
    """NFC normalization prevents duplicate UUIDs from different Unicode forms."""

    def test_user_id_nfc_composed_equals_decomposed(self) -> None:
        import unicodedata

        composed = "caf\u00e9"  # precomposed e-acute
        decomposed = unicodedata.normalize("NFD", composed)
        assert composed != decomposed  # sanity: they are different byte sequences
        assert generate_user_id(composed, "") == generate_user_id(decomposed, "")

    def test_host_id_nfc_composed_equals_decomposed(self) -> None:
        import unicodedata

        composed = "h\u00f6st"  # precomposed o-umlaut
        decomposed = unicodedata.normalize("NFD", composed)
        assert composed != decomposed
        assert generate_host_id(composed) == generate_host_id(decomposed)

    def test_file_id_nfc_composed_equals_decomposed(self) -> None:
        import unicodedata

        from seerflow.models.entity import generate_file_id

        composed = "/tmp/caf\u00e9.log"
        decomposed = unicodedata.normalize("NFD", composed)
        assert composed != decomposed
        assert generate_file_id(composed) == generate_file_id(decomposed)

    def test_domain_id_nfc_composed_equals_decomposed(self) -> None:
        import unicodedata

        from seerflow.models.entity import generate_domain_id

        composed = "caf\u00e9.com"
        decomposed = unicodedata.normalize("NFD", composed)
        assert composed != decomposed
        assert generate_domain_id(composed) == generate_domain_id(decomposed)


class TestInferEntityTypeExtended:
    """Tests for 6-type priority in infer_entity_type()."""

    def _make_event(self, **kwargs: tuple[str, ...]) -> SeerflowEvent:
        import uuid as _uuid

        return SeerflowEvent(
            event_id=_uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            severity_id=6,
            message="test",
            source_type="syslog",
            **kwargs,
        )

    def test_domain_when_no_ip_user_host(self) -> None:
        event = self._make_event(related_domains=("evil.com",))
        assert infer_entity_type(event) == "domain"

    def test_file_when_no_ip_user_host_domain(self) -> None:
        event = self._make_event(related_files=("/etc/passwd",))
        assert infer_entity_type(event) == "file"

    def test_process_when_no_other_types(self) -> None:
        event = self._make_event(related_processes=("sshd:1234",))
        assert infer_entity_type(event) == "process"

    def test_domain_loses_to_host(self) -> None:
        event = self._make_event(
            related_hosts=("web-01",),
            related_domains=("evil.com",),
        )
        assert infer_entity_type(event) == "host"

    def test_malformed_ip_falls_through_to_user(self) -> None:
        event = self._make_event(
            related_ips=("not-an-ip",),
            related_users=("admin",),
        )
        assert infer_entity_type(event) == "user"


class TestSanitizeForLog:
    def test_strips_newline(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\nb") == "a\\nb"

    def test_strips_carriage_return(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\rb") == "a\\rb"

    def test_strips_ansi_escape(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\x1bb") == "a\\x1bb"

    def test_strips_tab(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\tb") == "a\\tb"

    def test_strips_null_byte(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\x00b") == "a\\x00b"

    def test_strips_unicode_line_separator(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\u2028b") == "a\\u2028b"

    def test_strips_unicode_paragraph_separator(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("a\u2029b") == "a\\u2029b"

    def test_clean_string_unchanged(self) -> None:
        from seerflow.models.entity import sanitize_for_log

        assert sanitize_for_log("hello world") == "hello world"


class TestPrimaryEntityValueExtended:
    """Tests for 6-type primary_entity_value()."""

    def _make_event(self, **kwargs: tuple[str, ...]) -> SeerflowEvent:
        import uuid as _uuid

        return SeerflowEvent(
            event_id=_uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            severity_id=6,
            message="test",
            source_type="syslog",
            **kwargs,
        )

    def test_returns_domain_value(self) -> None:
        event = self._make_event(related_domains=("evil.com",))
        assert primary_entity_value(event) == "evil.com"

    def test_returns_file_value(self) -> None:
        event = self._make_event(related_files=("/etc/passwd",))
        assert primary_entity_value(event) == "/etc/passwd"

    def test_returns_process_value(self) -> None:
        event = self._make_event(related_processes=("sshd:1234",))
        assert primary_entity_value(event) == "sshd:1234"

    def test_malformed_ip_falls_through_to_user(self) -> None:
        event = self._make_event(
            related_ips=("not-an-ip",),
            related_users=("admin",),
        )
        assert primary_entity_value(event) == "admin"

    def test_malformed_ip_falls_through_to_domain(self) -> None:
        event = self._make_event(
            related_ips=("not-an-ip",),
            related_domains=("evil.com",),
        )
        assert primary_entity_value(event) == "evil.com"

    def test_valid_ip_returned_normally(self) -> None:
        event = self._make_event(
            related_ips=("10.0.1.1",),
            related_users=("admin",),
        )
        assert primary_entity_value(event) == "10.0.1.1"
