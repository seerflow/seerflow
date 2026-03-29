"""Tests for EntityExtractor — regex entity extraction."""

from __future__ import annotations

import pytest

from seerflow.parsing.entities import (
    EntityExtractor,
    TaggedEntity,
    _extract_domains,
    _extract_files,
    _extract_hosts,
    _extract_ips,
    _extract_processes,
    _extract_users,
)


class TestIPExtraction:
    def test_extract_ipv4(self) -> None:
        result = _extract_ips("from 192.168.1.1 to 10.0.0.1")
        assert "192.168.1.1" in result
        assert "10.0.0.1" in result

    def test_ipv4_valid_octets_only(self) -> None:
        result = _extract_ips("version 999.999.999.999")
        assert result == []

    def test_extract_ipv6_full(self) -> None:
        result = _extract_ips("addr 2001:db8:85a3::8a2e:370:7334")
        assert len(result) >= 1

    def test_extract_ipv6_loopback(self) -> None:
        result = _extract_ips("localhost ::1 connection")
        assert "::1" in result

    def test_no_ips(self) -> None:
        assert _extract_ips("plain text message") == []

    def test_dedup_ips(self) -> None:
        result = _extract_ips("from 10.0.0.1 to 10.0.0.1")
        assert result == ["10.0.0.1"]


class TestUserExtraction:
    def test_user_equals(self) -> None:
        assert "admin" in _extract_users("user=admin login")

    def test_user_for(self) -> None:
        assert "john.doe" in _extract_users("Login failed for user john.doe")

    def test_by_default_not_extracted_as_user(self) -> None:
        assert _extract_users("disabled by default") == []

    def test_user_space_not_too_loose(self) -> None:
        result = _extract_users("user account disabled")
        assert "account" not in result

    def test_no_users(self) -> None:
        assert _extract_users("plain text") == []

    def test_dedup_users(self) -> None:
        result = _extract_users("user=admin for user admin")
        assert result.count("admin") == 1


class TestHostExtraction:
    def test_hostname(self) -> None:
        result = _extract_hosts("connecting to host web-01.prod.internal")
        assert any("web-01" in h for h in result)

    def test_hostname_equals(self) -> None:
        result = _extract_hosts("hostname=app-server-01")
        assert "app-server-01" in result

    def test_on_monday_not_extracted_as_host(self) -> None:
        assert _extract_hosts("meeting on monday") == []

    def test_host_does_not_capture_ip(self) -> None:
        result = _extract_hosts("host=10.0.0.1 connected")
        assert "10.0.0.1" not in result

    def test_no_hosts(self) -> None:
        assert _extract_hosts("plain text message") == []


class TestFileExtraction:
    def test_absolute_path(self) -> None:
        assert "/var/log/syslog" in _extract_files("reading /var/log/syslog")

    def test_path_with_extension(self) -> None:
        assert "/etc/nginx/nginx.conf" in _extract_files("config /etc/nginx/nginx.conf loaded")

    def test_no_relative_paths(self) -> None:
        assert _extract_files("file data/log.txt") == []

    def test_no_files(self) -> None:
        assert _extract_files("plain text") == []


class TestDomainExtraction:
    def test_domain(self) -> None:
        assert "example.com" in _extract_domains("connecting to example.com")

    def test_subdomain(self) -> None:
        result = _extract_domains("host api.seerflow.dev responded")
        assert any("seerflow.dev" in d for d in result)

    def test_domain_does_not_match_file_extensions(self) -> None:
        result = _extract_domains("/var/log/nginx.conf is loaded")
        assert "nginx.conf" not in result

    def test_no_domains(self) -> None:
        assert _extract_domains("local connection") == []


class TestEntityExtractor:
    def test_extract_all_types(self) -> None:
        msg = "user=admin from 192.168.1.1 reading /var/log/syslog on web-01 via api.example.com"
        ext = EntityExtractor()
        result = ext.extract(msg)
        assert "ip" in result
        assert "user" in result
        assert "file" in result

    def test_empty_message(self) -> None:
        result = EntityExtractor().extract("")
        assert all(v == [] for v in result.values())

    def test_configurable_types(self) -> None:
        ext = EntityExtractor(enabled_types=frozenset({"ip"}))
        result = ext.extract("user=admin from 10.0.0.1")
        assert "ip" in result
        assert "user" not in result

    def test_default_all_types(self) -> None:
        result = EntityExtractor().extract("test")
        assert set(result.keys()) == {"ip", "user", "host", "file", "domain", "process"}

    def test_dedup(self) -> None:
        result = EntityExtractor().extract("10.0.0.1 10.0.0.1 10.0.0.1")
        assert len(result["ip"]) == 1

    def test_invalid_enabled_types_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown entity types"):
            EntityExtractor(enabled_types=frozenset({"ip", "banana"}))

    def test_long_message_truncated(self) -> None:
        ext = EntityExtractor()
        long_msg = "10.0.0.1 " * 100_000
        result = ext.extract(long_msg)
        assert isinstance(result, dict)

    def test_returns_dict(self) -> None:
        result = EntityExtractor().extract("test")
        assert isinstance(result, dict)


class TestEntityCountCap:
    def test_entity_count_capped(self) -> None:
        """Message with 100 distinct IPs returns exactly MAX_ENTITIES_PER_TYPE."""
        from seerflow.parsing._constants import MAX_ENTITIES_PER_TYPE

        ips = [f"10.0.{i // 256}.{i % 256}" for i in range(100)]
        message = " ".join(ips)
        ext = EntityExtractor(enabled_types=frozenset({"ip"}))
        result = ext.extract(message)
        assert len(result["ip"]) == MAX_ENTITIES_PER_TYPE

    def test_small_entity_count_not_capped(self) -> None:
        """Message with 3 IPs returns all 3."""
        ext = EntityExtractor(enabled_types=frozenset({"ip"}))
        result = ext.extract("from 10.0.0.1 to 10.0.0.2 via 10.0.0.3")
        assert len(result["ip"]) == 3


class TestEntityExports:
    def test_import_from_parsing_package(self) -> None:
        from seerflow.parsing import EntityExtractor as Cls

        assert Cls is EntityExtractor

    def test_in_all(self) -> None:
        import seerflow.parsing as pkg

        assert "EntityExtractor" in pkg.__all__


class TestProcessExtraction:
    def test_syslog_format(self) -> None:
        result = _extract_processes("Mar 22 sshd[1234]: Failed password")
        assert "sshd:1234" in result

    def test_pid_equals(self) -> None:
        result = _extract_processes("pid=5678 exited")
        assert "5678" in result

    def test_process_equals(self) -> None:
        result = _extract_processes("process=nginx started")
        assert "nginx" in result

    def test_process_name_equals(self) -> None:
        result = _extract_processes("process_name=httpd running")
        assert "httpd" in result

    def test_no_processes(self) -> None:
        assert _extract_processes("plain text message") == []

    def test_dedup(self) -> None:
        result = _extract_processes("sshd[1234]: ok sshd[1234]: ok")
        assert result.count("sshd:1234") == 1

    def test_multiple_patterns(self) -> None:
        result = _extract_processes("sshd[1234]: ok process=nginx")
        assert len(result) == 2

    def test_max_entities_cap(self) -> None:
        from seerflow.parsing._constants import MAX_ENTITIES_PER_TYPE

        ext = EntityExtractor()
        msg = " ".join(f"proc{i}[{i}]: ok" for i in range(MAX_ENTITIES_PER_TYPE + 10))
        result = ext.extract(msg)
        assert len(result["process"]) <= MAX_ENTITIES_PER_TYPE

    def test_array_index_not_matched(self) -> None:
        assert _extract_processes("array[0] processed items[42]") == []

    def test_syslog_requires_colon_or_whitespace(self) -> None:
        result = _extract_processes("sshd[1234]: login failed")
        assert "sshd:1234" in result


class TestExtractTagged:
    def test_with_params_tags_entities(self) -> None:
        """Entities found in params are tagged 'param', others 'template'."""
        extractor = EntityExtractor()
        result = extractor.extract_tagged(
            "Failed login for user admin from 10.0.0.1",
            params=("admin", "10.0.0.1"),
        )
        ips = result["ip"]
        assert len(ips) == 1
        assert ips[0].value == "10.0.0.1"
        assert ips[0].source == "param"

        users = result["user"]
        assert len(users) == 1
        assert users[0].value == "admin"
        assert users[0].source == "param"

    def test_without_params_tags_unknown(self) -> None:
        """Without params, all entities tagged 'unknown'."""
        extractor = EntityExtractor()
        result = extractor.extract_tagged("Login from 10.0.0.1")
        ips = result["ip"]
        assert len(ips) == 1
        assert ips[0].source == "unknown"

    def test_static_entity_tagged_template(self) -> None:
        """Entity NOT in params is tagged 'template'."""
        extractor = EntityExtractor()
        result = extractor.extract_tagged(
            "Server 192.168.1.1 login from 10.0.0.1",
            params=("10.0.0.1",),
        )
        ips = result["ip"]
        param_ips = [e for e in ips if e.source == "param"]
        template_ips = [e for e in ips if e.source == "template"]
        assert len(param_ips) == 1
        assert param_ips[0].value == "10.0.0.1"
        assert len(template_ips) == 1
        assert template_ips[0].value == "192.168.1.1"

    def test_tagged_entity_is_frozen(self) -> None:
        """TaggedEntity is immutable."""
        entity = TaggedEntity(value="10.0.0.1", source="param")
        with pytest.raises(AttributeError):
            entity.value = "changed"  # type: ignore[misc]

    def test_backward_compat_extract_unchanged(self) -> None:
        """Original extract() still returns dict[str, list[str]]."""
        extractor = EntityExtractor()
        result = extractor.extract("Login from 10.0.0.1 by admin")
        assert isinstance(result["ip"][0], str)
