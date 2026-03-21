"""Tests for EntityExtractor — regex entity extraction."""

from __future__ import annotations

from seerflow.parsing.entities import (
    EntityExtractor,
    _extract_domains,
    _extract_files,
    _extract_hosts,
    _extract_ips,
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
        assert set(result.keys()) == {"ip", "user", "host", "file", "domain"}

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
