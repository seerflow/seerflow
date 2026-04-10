"""Tests for API dependency injection and timestamp parsing."""

from __future__ import annotations

import pytest

from seerflow.api.deps import StorageDeps, parse_timestamp_ns


class TestParseTimestampNs:
    """Tests for ISO-8601 -> nanosecond epoch conversion."""

    def test_utc_iso_string(self) -> None:
        result = parse_timestamp_ns("2026-04-09T12:00:00+00:00")
        assert result == 1_775_736_000_000_000_000

    def test_naive_assumed_utc(self) -> None:
        result = parse_timestamp_ns("2026-04-09T12:00:00")
        assert result == 1_775_736_000_000_000_000

    def test_with_timezone_offset(self) -> None:
        result = parse_timestamp_ns("2026-04-09T14:00:00+02:00")
        assert result == 1_775_736_000_000_000_000

    def test_with_fractional_seconds(self) -> None:
        result = parse_timestamp_ns("2026-04-09T12:00:00.500+00:00")
        assert result == 1_775_736_000_500_000_000

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_timestamp_ns("not-a-date")

    def test_far_future_overflows_raises(self) -> None:
        with pytest.raises(ValueError, match="out of supported range"):
            parse_timestamp_ns("9999-12-31T23:59:59+00:00")


class TestStorageDeps:
    """Tests for the StorageDeps container."""

    def test_entity_store_defaults_to_none(self) -> None:
        from unittest.mock import AsyncMock

        deps = StorageDeps(log_store=AsyncMock(), alert_store=AsyncMock())
        assert deps.entity_store is None

    def test_all_stores_set(self) -> None:
        from unittest.mock import AsyncMock

        deps = StorageDeps(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            entity_store=AsyncMock(),
        )
        assert deps.log_store is not None
        assert deps.alert_store is not None
        assert deps.entity_store is not None
