"""Tests for Drain3 template persistence — state serialization and restore."""

from __future__ import annotations

from unittest.mock import AsyncMock

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
        with pytest.raises(ValueError, match=r"[Dd]eserializ|[Cc]orrupt|[Ff]ail"):
            parser.load_state(b"not valid state data")

    def test_empty_bytes_raises_valueerror(self) -> None:
        parser = DrainParser()
        with pytest.raises(ValueError, match=r"[Ee]mpty|[Dd]eserializ"):
            parser.load_state(b"")


class TestLargeState:
    def test_many_templates_round_trip(self) -> None:
        parser = DrainParser(max_clusters=200)
        templates_before: dict[str, int] = {}
        for i in range(100):
            msg = f"Unique pattern {i} with value {i * 10} on host server{i % 5}"
            tid, _, _ = parser.parse(msg)
            templates_before[msg] = tid

        state = parser.get_state()
        assert len(state) > 100

        parser2 = DrainParser(max_clusters=200)
        parser2.load_state(state)
        assert parser2.template_count == parser.template_count

        for msg, expected_tid in list(templates_before.items())[:10]:
            tid, _, _ = parser2.parse(msg)
            assert tid == expected_tid


class TestSaveDrainState:
    async def test_save_calls_model_store(self) -> None:
        from seerflow.parsing.drain_persistence import save_drain_state

        parser = DrainParser()
        parser.parse("Login failed for user admin")

        store = AsyncMock()
        store.save_state = AsyncMock()

        await save_drain_state(parser, store)

        store.save_state.assert_called_once()
        key, data = store.save_state.call_args[0]
        assert key == "drain3:global"
        assert isinstance(data, bytes)
        assert len(data) > 0

    async def test_save_custom_key(self) -> None:
        from seerflow.parsing.drain_persistence import save_drain_state

        parser = DrainParser()
        parser.parse("test message")

        store = AsyncMock()
        store.save_state = AsyncMock()

        await save_drain_state(parser, store, key="drain3:source1")

        key, _ = store.save_state.call_args[0]
        assert key == "drain3:source1"


class TestLoadDrainState:
    async def test_load_returns_true_when_state_exists(self) -> None:
        from seerflow.parsing.drain_persistence import load_drain_state

        parser = DrainParser()
        parser.parse("Login failed for user admin")
        state = parser.get_state()

        store = AsyncMock()
        store.load_state = AsyncMock(return_value=state)

        parser2 = DrainParser()
        loaded = await load_drain_state(parser2, store)

        assert loaded is True
        assert parser2.template_count == parser.template_count
        store.load_state.assert_called_once_with("drain3:global")

    async def test_load_returns_false_when_no_state(self) -> None:
        from seerflow.parsing.drain_persistence import load_drain_state

        store = AsyncMock()
        store.load_state = AsyncMock(return_value=None)

        parser = DrainParser()
        loaded = await load_drain_state(parser, store)

        assert loaded is False
        assert parser.template_count == 0

    async def test_load_returns_false_on_corruption(self) -> None:
        from seerflow.parsing.drain_persistence import load_drain_state

        store = AsyncMock()
        store.load_state = AsyncMock(return_value=b"corrupted data")

        parser = DrainParser()
        loaded = await load_drain_state(parser, store)

        assert loaded is False
        assert parser.template_count == 0

    async def test_load_custom_key(self) -> None:
        from seerflow.parsing.drain_persistence import load_drain_state

        parser = DrainParser()
        parser.parse("test")
        state = parser.get_state()

        store = AsyncMock()
        store.load_state = AsyncMock(return_value=state)

        parser2 = DrainParser()
        await load_drain_state(parser2, store, key="drain3:custom")

        store.load_state.assert_called_once_with("drain3:custom")


class TestExports:
    def test_import_from_parsing(self) -> None:
        from seerflow.parsing import load_drain_state, save_drain_state

        assert callable(load_drain_state)
        assert callable(save_drain_state)

    def test_all_contains_persistence_functions(self) -> None:
        import seerflow.parsing as mod

        assert "load_drain_state" in mod.__all__
        assert "save_drain_state" in mod.__all__
