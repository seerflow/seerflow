"""Unit tests for EngineHolder — mutable wrapper for hot-swappable engines."""

from __future__ import annotations

from seerflow.correlation.holders import EngineHolder


class TestEngineHolder:
    """Tests for EngineHolder generic dataclass."""

    def test_create_with_engine(self) -> None:
        """EngineHolder stores the initial engine reference."""
        holder: EngineHolder[str] = EngineHolder(engine="v1")
        assert holder.engine == "v1"

    def test_replace_engine(self) -> None:
        """EngineHolder allows atomic engine replacement."""
        holder: EngineHolder[str] = EngineHolder(engine="v1")
        holder.engine = "v2"
        assert holder.engine == "v2"

    def test_none_engine(self) -> None:
        """EngineHolder supports None as an engine value."""
        holder: EngineHolder[None] = EngineHolder(engine=None)
        assert holder.engine is None

    def test_optional_engine_type(self) -> None:
        """EngineHolder with Optional type starts with engine then swaps to None."""
        holder: EngineHolder[str | None] = EngineHolder(engine="initial")
        assert holder.engine == "initial"
        holder.engine = None
        assert holder.engine is None

    def test_generic_type_preserved(self) -> None:
        """EngineHolder works with complex types."""
        holder: EngineHolder[list[int]] = EngineHolder(engine=[1, 2, 3])
        assert holder.engine == [1, 2, 3]
        holder.engine = [4, 5]
        assert holder.engine == [4, 5]

    def test_is_dataclass(self) -> None:
        """EngineHolder is a dataclass (not frozen — mutable by design)."""
        from dataclasses import fields

        holder = EngineHolder(engine="x")
        field_names = [f.name for f in fields(holder)]
        assert field_names == ["engine"]

    def test_equality(self) -> None:
        """EngineHolder with same engine value is equal."""
        a: EngineHolder[int] = EngineHolder(engine=42)
        b: EngineHolder[int] = EngineHolder(engine=42)
        assert a == b

    def test_repr(self) -> None:
        """EngineHolder has a readable repr."""
        holder = EngineHolder(engine="sigma-v1")
        assert "sigma-v1" in repr(holder)
