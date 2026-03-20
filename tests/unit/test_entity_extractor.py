"""Tests for EntityExtractor — regex entity extraction."""

from __future__ import annotations

from seerflow.parsing.entities import _extract_ips


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
