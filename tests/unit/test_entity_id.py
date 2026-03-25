"""Tests for UUID5 identity generators and normalize_username."""

from __future__ import annotations

import uuid

import pytest

from seerflow.models.entity import (
    NS_DOMAIN,
    NS_FILE,
    NS_HOST,
    NS_IP,
    NS_PROCESS,
    NS_USER,
    generate_domain_id,
    generate_file_id,
    generate_host_id,
    generate_ip_id,
    generate_process_id,
    generate_user_id,
    normalize_username,
)


class TestNormalizeUsername:
    def test_backslash_format(self) -> None:
        assert normalize_username(r"CORP\alice") == ("alice", "corp")

    def test_at_format(self) -> None:
        assert normalize_username("alice@corp.local") == ("alice", "corp.local")

    def test_bare_username(self) -> None:
        assert normalize_username("alice") == ("alice", "")

    def test_bare_with_default_domain(self) -> None:
        assert normalize_username("alice", "corp.local") == ("alice", "corp.local")

    def test_whitespace_stripped(self) -> None:
        assert normalize_username("  alice  ") == ("alice", "")

    def test_lowercase(self) -> None:
        assert normalize_username("ALICE") == ("alice", "")


class TestGenerateUserId:
    def test_deterministic(self) -> None:
        a = generate_user_id("alice", "corp")
        b = generate_user_id("alice", "corp")
        assert a == b

    def test_different_users_differ(self) -> None:
        assert generate_user_id("alice", "corp") != generate_user_id("bob", "corp")

    def test_domain_changes_id(self) -> None:
        assert generate_user_id("alice", "a.com") != generate_user_id("alice", "b.com")

    def test_empty_domain_uses_username_only(self) -> None:
        uid = generate_user_id("alice", "")
        assert uid == uuid.uuid5(NS_USER, "alice")

    def test_with_domain(self) -> None:
        uid = generate_user_id("alice", "corp")
        assert uid == uuid.uuid5(NS_USER, "corp:alice")

    def test_whitespace_stripped_from_username(self) -> None:
        assert generate_user_id(" alice ", "corp") == generate_user_id("alice", "corp")

    def test_empty_username_empty_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_user_id("", "")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_user_id("   ", "")

    def test_whitespace_username_with_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_user_id("   ", "corp")


class TestGenerateIpId:
    def test_ipv4_deterministic(self) -> None:
        a = generate_ip_id("10.0.0.1")
        b = generate_ip_id("10.0.0.1")
        assert a == b

    def test_ipv4_canonical(self) -> None:
        assert generate_ip_id("10.0.0.1") == uuid.uuid5(NS_IP, "10.0.0.1")

    def test_ipv6_loopback(self) -> None:
        uid = generate_ip_id("::1")
        assert uid == uuid.uuid5(NS_IP, "0000:0000:0000:0000:0000:0000:0000:0001")

    def test_ipv6_all_zeros(self) -> None:
        uid = generate_ip_id("::")
        assert uid == uuid.uuid5(NS_IP, "0000:0000:0000:0000:0000:0000:0000:0000")

    def test_ipv6_full_form(self) -> None:
        uid = generate_ip_id("2001:db8::1")
        assert uid == uuid.uuid5(NS_IP, "2001:0db8:0000:0000:0000:0000:0000:0001")

    def test_whitespace_stripped(self) -> None:
        assert generate_ip_id("  10.0.0.1  ") == generate_ip_id("10.0.0.1")

    def test_invalid_ip_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_ip_id("not-an-ip")


class TestGenerateHostId:
    def test_deterministic(self) -> None:
        assert generate_host_id("web01") == generate_host_id("web01")

    def test_case_insensitive(self) -> None:
        assert generate_host_id("WEB01") == generate_host_id("web01")

    def test_bare_hostname_with_domain(self) -> None:
        uid = generate_host_id("web01", "corp.local")
        assert uid == uuid.uuid5(NS_HOST, "web01.corp.local")

    def test_fqdn_ignores_domain(self) -> None:
        uid = generate_host_id("web01.corp.local", "other.com")
        assert uid == uuid.uuid5(NS_HOST, "web01.corp.local")

    def test_trailing_dot_stripped(self) -> None:
        assert generate_host_id("web01.") == generate_host_id("web01")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_host_id("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_host_id("   ")


class TestGenerateProcessId:
    def test_deterministic(self) -> None:
        a = generate_process_id("web01", 1234, 1700000000)
        b = generate_process_id("web01", 1234, 1700000000)
        assert a == b

    def test_canonical_form(self) -> None:
        uid = generate_process_id("web01", 1234, 1700000000)
        assert uid == uuid.uuid5(NS_PROCESS, "web01:1234:1700000000")

    def test_different_pid_differs(self) -> None:
        assert generate_process_id("h", 1, 0) != generate_process_id("h", 2, 0)

    def test_negative_pid_raises(self) -> None:
        with pytest.raises(ValueError, match="pid"):
            generate_process_id("h", -1, 0)

    def test_pid_zero_allowed(self) -> None:
        generate_process_id("h", 0, 0)


class TestGenerateFileId:
    def test_deterministic(self) -> None:
        assert generate_file_id("/var/log/syslog") == generate_file_id("/var/log/syslog")

    def test_canonical(self) -> None:
        assert generate_file_id("/var/log/syslog") == uuid.uuid5(NS_FILE, "/var/log/syslog")

    def test_whitespace_stripped(self) -> None:
        assert generate_file_id("  /a  ") == generate_file_id("/a")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_file_id("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_file_id("   ")


class TestGenerateDomainId:
    def test_deterministic(self) -> None:
        assert generate_domain_id("example.com") == generate_domain_id("example.com")

    def test_case_insensitive(self) -> None:
        assert generate_domain_id("Example.COM") == generate_domain_id("example.com")

    def test_trailing_dot_stripped(self) -> None:
        assert generate_domain_id("example.com.") == generate_domain_id("example.com")

    def test_canonical(self) -> None:
        assert generate_domain_id("example.com") == uuid.uuid5(NS_DOMAIN, "example.com")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_domain_id("")

    def test_dot_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_domain_id(".")
