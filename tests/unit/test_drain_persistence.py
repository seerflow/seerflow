"""Tests for Drain3 template persistence — state serialization and restore."""

from __future__ import annotations

import pytest

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


class TestLoadState:
    def test_round_trip(self) -> None:
        parser = DrainParser()
        parser.parse("Login failed for user admin")
        parser.parse("Connection established to database")
        state = parser.get_state()

        parser2 = DrainParser()
        parser2.load_state(state)
        assert parser2.template_count == parser.template_count

    def test_id_stability(self) -> None:
        parser = DrainParser()
        tid1, _, _ = parser.parse("Login failed for user alice")
        parser.parse("Connection established to db01")
        state = parser.get_state()

        parser2 = DrainParser()
        parser2.load_state(state)
        tid2, _, _ = parser2.parse("Login failed for user bob")
        assert tid1 == tid2  # same template, same ID after restore

    def test_no_id_collision(self) -> None:
        parser = DrainParser()
        parser.parse("Login failed for user admin")
        parser.parse("Connection established to database")
        state = parser.get_state()
        existing_count = parser.template_count

        parser2 = DrainParser()
        parser2.load_state(state)
        tid_new, _, _ = parser2.parse("Completely new unique pattern xyz")
        assert tid_new > 0
        assert parser2.template_count == existing_count + 1

    def test_corrupted_bytes_raises_valueerror(self) -> None:
        parser = DrainParser()
        with pytest.raises(ValueError, match="[Dd]eserializ|[Cc]orrupt|[Ff]ail"):
            parser.load_state(b"not valid state data")

    def test_empty_bytes_raises_valueerror(self) -> None:
        parser = DrainParser()
        with pytest.raises(ValueError, match="[Ee]mpty|[Dd]eserializ"):
            parser.load_state(b"")
