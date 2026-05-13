"""Tests for LANL anonymized hostname → deterministic private IP mapper."""

from __future__ import annotations

import pytest

from seerflow.lanl.hostmap import host_to_ip


class TestHostToIp:
    def test_simple_host(self) -> None:
        assert host_to_ip("C1") == "10.0.0.1"

    def test_medium_host(self) -> None:
        # 528 = 0x210 → 10.0.2.16
        assert host_to_ip("C528") == "10.0.2.16"

    def test_large_host(self) -> None:
        # 17693 = 0x451D → 10.0.69.29
        assert host_to_ip("C17693") == "10.0.69.29"

    def test_c256(self) -> None:
        # 256 = 0x100 → 10.0.1.0
        assert host_to_ip("C256") == "10.0.1.0"

    def test_deterministic(self) -> None:
        result_a = host_to_ip("C12345")
        result_b = host_to_ip("C12345")
        assert result_a == result_b

    def test_invalid_host_no_prefix_raises(self) -> None:
        with pytest.raises(ValueError):
            host_to_ip("INVALID")

    def test_invalid_host_wrong_prefix_raises(self) -> None:
        with pytest.raises(ValueError):
            host_to_ip("X123")

    def test_invalid_host_lowercase_c_raises(self) -> None:
        with pytest.raises(ValueError):
            host_to_ip("c1")

    def test_invalid_host_trailing_chars_raises(self) -> None:
        with pytest.raises(ValueError):
            host_to_ip("C123abc")

    def test_empty_host_raises(self) -> None:
        with pytest.raises(ValueError):
            host_to_ip("")

    def test_overflow_raises(self) -> None:
        # 16777216 = 0x1000000 — one more than 3-byte max
        with pytest.raises(ValueError):
            host_to_ip("C16777216")

    def test_max_valid_host(self) -> None:
        # 16777215 = 0xFFFFFF — exactly fits in 3 bytes → 10.255.255.255
        assert host_to_ip("C16777215") == "10.255.255.255"

    def test_c_zero_raises(self) -> None:
        # C0 is not valid — N must be a positive integer
        with pytest.raises(ValueError):
            host_to_ip("C0")
