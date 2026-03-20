"""Tests for EntityExtractor — regex entity extraction."""

from __future__ import annotations

from seerflow.parsing.entities import (
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

    def test_user_by(self) -> None:
        assert "root" in _extract_users("authenticated by root")

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

    def test_no_domains(self) -> None:
        assert _extract_domains("local connection") == []
