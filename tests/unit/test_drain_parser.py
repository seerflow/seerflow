"""Tests for DrainParser — template extraction, masking, params."""
from __future__ import annotations

from seerflow.parsing.drain import _mask_tokens


class TestRegexMasking:
    def test_mask_ipv4(self) -> None:
        assert _mask_tokens("from 192.168.1.5 to 10.0.0.1") == "from <IP> to <IP>"

    def test_mask_single_ip(self) -> None:
        assert "<IP>" in _mask_tokens("host 172.16.0.1 connected")

    def test_mask_uuid(self) -> None:
        result = _mask_tokens("request a1b2c3d4-e5f6-7890-abcd-ef1234567890 completed")
        assert "<UUID>" in result
        assert "a1b2c3d4" not in result

    def test_mask_no_match(self) -> None:
        assert _mask_tokens("plain text message") == "plain text message"

    def test_mask_combined(self) -> None:
        result = _mask_tokens("host 10.0.0.1 req 550e8400-e29b-41d4-a716-446655440000")
        assert "<IP>" in result
        assert "<UUID>" in result
