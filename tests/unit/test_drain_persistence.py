"""Tests for Drain3 template persistence — state serialization and restore."""

from __future__ import annotations

from seerflow.parsing.drain import DrainParser


class TestGetState:
    def test_get_state_returns_bytes(self) -> None:
        parser = DrainParser()
        parser.parse("Login failed for user admin")
        state = parser.get_state()
        assert isinstance(state, bytes)
        assert len(state) > 0

    def test_get_state_empty_parser(self) -> None:
        parser = DrainParser()
        state = parser.get_state()
        assert isinstance(state, bytes)
        assert len(state) > 0  # even empty Drain tree serializes
